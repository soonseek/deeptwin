#import <Foundation/Foundation.h>
#import <Security/Security.h>

@protocol NativeCanary
- (void)perform:(NSData *)request withReply:(void (^)(NSData *))reply;
@end

static inline NSData *Encode(id value) {
    return [NSJSONSerialization dataWithJSONObject:value options:0 error:NULL];
}

static inline NSDictionary *Decode(NSData *value) {
    if (![value isKindOfClass:[NSData class]] || value.length > 65536) return nil;
    id decoded = [NSJSONSerialization JSONObjectWithData:value options:0 error:NULL];
    return [decoded isKindOfClass:[NSDictionary class]] ? decoded : nil;
}

static inline NSXPCInterface *CanaryInterface(void) {
    NSXPCInterface *interface = [NSXPCInterface interfaceWithProtocol:@protocol(NativeCanary)];
    NSSet *classes = [NSSet setWithObject:[NSData class]];
    [interface setClasses:classes forSelector:@selector(perform:withReply:) argumentIndex:0 ofReply:NO];
    [interface setClasses:classes forSelector:@selector(perform:withReply:) argumentIndex:0 ofReply:YES];
    return interface;
}

static inline NSString *CodeRequirement(NSURL *url) {
    SecStaticCodeRef code = NULL;
    CFDictionaryRef info = NULL;
    if (SecStaticCodeCreateWithPath((__bridge CFURLRef)url, kSecCSDefaultFlags, &code) != errSecSuccess) return nil;
    OSStatus status = SecCodeCopySigningInformation(code, kSecCSSigningInformation, &info);
    CFRelease(code);
    if (status != errSecSuccess || !info) return nil;
    NSDictionary *dict = CFBridgingRelease(info);
    NSData *hash = dict[(__bridge NSString *)kSecCodeInfoUnique];
    if (![hash isKindOfClass:[NSData class]] || hash.length != 20) return nil;
    NSMutableString *hex = [NSMutableString string];
    for (NSUInteger n = 0; n < hash.length; n++) [hex appendFormat:@"%02x", ((const unsigned char *)hash.bytes)[n]];
    return [NSString stringWithFormat:@"cdhash H\"%@\"", hex];
}

static inline NSString *NeverRequirement(void) {
    return @"cdhash H\"0000000000000000000000000000000000000000\"";
}
