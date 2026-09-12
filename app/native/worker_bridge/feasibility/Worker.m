#import "Checks.h"

@interface Worker : NSObject <NativeCanary, NSXPCListenerDelegate>
@property(nonatomic, strong) NSTask *child;
@property(nonatomic, copy) NSString *generation;
@property(nonatomic, copy) NSString *hostRequirement;
@property(nonatomic, strong) NSDictionary *guestObservation;
@end

@implementation Worker
- (BOOL)listener:(NSXPCListener *)listener shouldAcceptNewConnection:(NSXPCConnection *)connection {
    (void)listener;
    if (self.hostRequirement) [connection setCodeSigningRequirement:self.hostRequirement];
    // Observational only: PID-derived signing info is NOT a trusted peer bootstrap.
    SecCodeRef guest = NULL; CFDictionaryRef info = NULL;
    OSStatus lookup = SecCodeCopyGuestWithAttributes(NULL,
        (__bridge CFDictionaryRef)@{(__bridge NSString *)kSecGuestAttributePid: @(connection.processIdentifier)},
        kSecCSDefaultFlags, &guest);
    OSStatus signing = guest ? SecCodeCopySigningInformation(guest, kSecCSDynamicInformation | kSecCSSigningInformation, &info) : lookup;
    if (guest) CFRelease(guest);
    NSDictionary *dict = info ? CFBridgingRelease(info) : @{};
    NSData *hash = dict[(__bridge NSString *)kSecCodeInfoUnique];
    NSMutableString *hex = [NSMutableString string];
    if ([hash isKindOfClass:NSData.class]) for (NSUInteger n = 0; n < hash.length; n++)
        [hex appendFormat:@"%02x", ((const unsigned char *)hash.bytes)[n]];
    self.guestObservation = @{@"lookup_status": @(lookup), @"signing_info_status": @(signing),
        @"observed_cdhash": hex, @"pid": @(connection.processIdentifier), @"authenticated": @NO};
    connection.exportedInterface = CanaryInterface(); connection.exportedObject = self;
    [connection activate]; return YES;
}
- (void)perform:(NSData *)request withReply:(void (^)(NSData *))reply {
    NSDictionary *message = Decode(request);
    if (!message || message.count != 2 || ![message[@"action"] isKindOfClass:[NSString class]]
        || ![message[@"config"] isKindOfClass:[NSDictionary class]] || !ConfigValid(message[@"config"])) {
        reply(Encode(@{@"error": @"invalid_request"})); return;
    }
    NSDictionary *config = message[@"config"];
    if (self.generation && ![self.generation isEqual:config[@"generation"]]) {
        reply(Encode(@{@"error": @"stale_generation"})); return;
    }
    self.generation = config[@"generation"];
    NSString *action = message[@"action"];
    if ([action isEqual:@"exit"]) { _exit(0); }
    if ([action isEqual:@"hello"]) { reply(Encode(@{@"ready": @YES, @"pid": @(getpid())})); return; }
    if (![action isEqual:@"native"]) { reply(Encode(@{@"error": @"unknown_action"})); return; }
    NSDictionary *worker = RunChecks(config, @"worker");
    NSTask *task = [NSTask new]; self.child = task;
    NSURL *bundle = NSBundle.mainBundle.bundleURL;
    task.executableURL = [bundle URLByAppendingPathComponent:@"Contents/Helpers/DeepTwinProbe"];
    task.environment = @{@"LANG": @"en_US.UTF-8"};
    NSPipe *input = [NSPipe pipe], *output = [NSPipe pipe];
    task.standardInput = input; task.standardOutput = output; task.standardError = [NSFileHandle fileHandleWithNullDevice];
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) { reply(Encode(@{@"worker": worker, @"error": @"child_launch_failed", @"code": @(error.code)})); return; }
    [input.fileHandleForWriting writeData:Encode(config)]; [input.fileHandleForWriting closeFile];
    NSData *bytes = [output.fileHandleForReading readDataToEndOfFile];
    [task waitUntilExit]; self.child = nil;
    reply(Encode(@{@"worker": worker, @"child": Decode(bytes) ?: @{}, @"peer_auth_complete": @NO,
        @"guest_observation": self.guestObservation ?: @{},
        @"child_exited": @((BOOL)!task.running), @"child_status": @(task.terminationStatus)}));
}
@end

int main(void) {
    @autoreleasepool {
        Worker *worker = [Worker new];
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 45 * NSEC_PER_SEC), dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
            if (worker.child.running) [worker.child terminate];
            _exit(124);
        });
        // N0 ONLY: collect OS-denial evidence while host authentication stays unqualified.
        // The production dispatcher must never use this canary service.
        worker.hostRequirement = [NSBundle.mainBundle.infoDictionary[@"NativeDenyPeer"] boolValue] ? NeverRequirement() : nil;
        NSXPCListener *listener = NSXPCListener.serviceListener;
        listener.delegate = worker;
        [listener resume];
    }
    return 0;
}
