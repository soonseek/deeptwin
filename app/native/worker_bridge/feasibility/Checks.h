#import "Protocol.h"
#include <sys/socket.h>
#include <sys/stat.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>

static inline BOOL ConfigValid(NSDictionary *config) {
    if (![config[@"generation"] isKindOfClass:[NSString class]] || [config[@"generation"] length] != 32) return NO;
    if (![config[@"ports"] isKindOfClass:[NSDictionary class]] || [config[@"ports"] count] != 4) return NO;
    for (NSString *key in @[@"tcp4", @"tcp6", @"udp4", @"udp6"]) {
        id port = config[@"ports"][key];
        if (![port isKindOfClass:[NSNumber class]] || [port intValue] < 1024 || [port intValue] > 65535) return NO;
    }
    NSString *path = config[@"private_path"], *root = config[@"fixture_root"];
    if (![path isKindOfClass:[NSString class]] || ![root isKindOfClass:[NSString class]]) return NO;
    return [root containsString:@"/Library/Application Support/DeepTwinCanaryFixtures/deeptwin-n0-"]
        && [path isEqual:[root stringByAppendingPathComponent:@"synthetic-private.txt"]]
        && [path isEqual:path.stringByStandardizingPath];
}

static inline NSDictionary *SocketProbe(NSString *key, int port, NSString *role) {
    BOOL ipv6 = [key hasSuffix:@"6"], udp = [key hasPrefix:@"udp"];
    int fd = socket(ipv6 ? AF_INET6 : AF_INET, udp ? SOCK_DGRAM : SOCK_STREAM, 0);
    int saved = errno;
    BOOL ok = NO;
    if (fd >= 0) {
        struct timeval timeout = {.tv_sec = 1, .tv_usec = 0};
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
        struct sockaddr_storage storage = {0};
        socklen_t length;
        if (ipv6) {
            struct sockaddr_in6 *a = (void *)&storage;
            a->sin6_family = AF_INET6; a->sin6_port = htons(port); a->sin6_addr = in6addr_loopback;
            length = sizeof(*a);
        } else {
            struct sockaddr_in *a = (void *)&storage;
            a->sin_family = AF_INET; a->sin_port = htons(port); a->sin_addr.s_addr = htonl(INADDR_LOOPBACK);
            length = sizeof(*a);
        }
        NSData *marker = [[NSString stringWithFormat:@"%@:%@", role, key] dataUsingEncoding:NSASCIIStringEncoding];
        if (udp) ok = sendto(fd, marker.bytes, marker.length, 0, (void *)&storage, length) == (ssize_t)marker.length;
        else if (connect(fd, (void *)&storage, length) == 0) ok = send(fd, marker.bytes, marker.length, 0) == (ssize_t)marker.length;
        saved = ok ? 0 : errno;
        close(fd);
    }
    return @{@"case": key, @"ok": @(ok), @"errno": @(saved)};
}

static inline BOOL SandboxEntitlement(void) {
    SecCodeRef code = NULL; CFDictionaryRef info = NULL;
    if (SecCodeCopySelf(kSecCSDefaultFlags, &code) != errSecSuccess) return NO;
    OSStatus status = SecCodeCopySigningInformation(code, kSecCSSigningInformation, &info);
    CFRelease(code);
    if (status != errSecSuccess || !info) return NO;
    NSDictionary *dict = CFBridgingRelease(info);
    return [dict[(__bridge NSString *)kSecCodeInfoEntitlementsDict][@"com.apple.security.app-sandbox"] boolValue];
}

static inline NSDictionary *BindProbe(NSString *key) {
    BOOL ipv6 = [key hasSuffix:@"6"], udp = [key hasPrefix:@"udp"];
    int fd = socket(ipv6 ? AF_INET6 : AF_INET, udp ? SOCK_DGRAM : SOCK_STREAM, 0);
    BOOL ok = NO; int saved = errno;
    if (fd >= 0) {
        struct sockaddr_storage storage = {0}; socklen_t length;
        if (ipv6) {
            struct sockaddr_in6 *a = (void *)&storage;
            a->sin6_family = AF_INET6; a->sin6_addr = in6addr_loopback; length = sizeof(*a);
        } else {
            struct sockaddr_in *a = (void *)&storage;
            a->sin_family = AF_INET; a->sin_addr.s_addr = htonl(INADDR_LOOPBACK); length = sizeof(*a);
        }
        ok = bind(fd, (void *)&storage, length) == 0;
        if (ok && !udp) ok = listen(fd, 1) == 0;
        saved = ok ? 0 : errno; close(fd);
    }
    return @{@"case": key, @"ok": @(ok), @"errno": @(saved)};
}

static inline NSDictionary *RunChecks(NSDictionary *config, NSString *role) {
    NSMutableArray *network = [NSMutableArray array];
    for (NSString *key in @[@"tcp4", @"tcp6", @"udp4", @"udp6"])
        [network addObject:SocketProbe(key, [config[@"ports"][key] intValue], role)];
    NSMutableArray *servers = [NSMutableArray array];
    for (NSString *key in @[@"tcp4", @"tcp6", @"udp4", @"udp6"]) [servers addObject:BindProbe(key)];
    NSString *private = config[@"private_path"];
    int fd = open(private.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW);
    int readError = errno;
    BOOL readOK = NO;
    if (fd >= 0) { char byte; readOK = read(fd, &byte, 1) == 1; close(fd); }
    fd = open(private.fileSystemRepresentation, O_WRONLY | O_APPEND | O_NOFOLLOW);
    int writeError = errno;
    BOOL writeOK = NO;
    if (fd >= 0) { writeOK = write(fd, "UNEXPECTED-CANARY-WRITE", 23) == 23; close(fd); }
    NSString *own = [NSTemporaryDirectory() stringByAppendingPathComponent:[NSString stringWithFormat:@"n0-%@.txt", NSUUID.UUID.UUIDString]];
    NSData *bytes = [@"owned-synthetic-canary" dataUsingEncoding:NSUTF8StringEncoding];
    BOOL ownOK = [bytes writeToFile:own options:NSDataWritingAtomic error:NULL]
        && [[NSData dataWithContentsOfFile:own] isEqual:bytes];
    if (ownOK) [[NSFileManager defaultManager] removeItemAtPath:own error:NULL];
    NSMutableArray *fds = [NSMutableArray array];
    for (int n = 0; n < 64; n++) {
        struct stat value;
        if (fstat(n, &value) == 0) [fds addObject:@{@"fd": @(n), @"type": @((value.st_mode & S_IFMT))}];
    }
    return @{@"role": role, @"pid": @(getpid()), @"parent_pid": @(getppid()),
        @"app_sandbox": @(SandboxEntitlement()), @"network": network, @"servers": servers,
        @"private_read_ok": @(readOK), @"private_read_errno": @(readError),
        @"private_write_ok": @(writeOK), @"private_write_errno": @(writeError),
        @"own_file_ok": @(ownOK), @"descriptors": fds};
}
