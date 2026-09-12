#import "Checks.h"

static NSDictionary *Call(NSXPCConnection *connection, NSData *request) {
    dispatch_semaphore_t semaphore = dispatch_semaphore_create(0);
    __block NSDictionary *result;
    id<NativeCanary> proxy = [connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        result = @{@"transport_error": @(error.code)}; dispatch_semaphore_signal(semaphore);
    }];
    [proxy perform:request withReply:^(NSData *reply) {
        result = Decode(reply) ?: @{@"error": @"invalid_reply"}; dispatch_semaphore_signal(semaphore);
    }];
    if (dispatch_semaphore_wait(semaphore, dispatch_time(DISPATCH_TIME_NOW, 12 * NSEC_PER_SEC)) != 0)
        return @{@"error": @"reply_timeout"};
    return result ?: @{@"error": @"missing_reply"};
}

static NSXPCConnection *Connect(NSString *name, NSString *requirement) {
    NSXPCConnection *connection = [[NSXPCConnection alloc] initWithServiceName:name];
    connection.remoteObjectInterface = CanaryInterface();
    [connection setCodeSigningRequirement:requirement]; [connection activate]; return connection;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        alarm(48);
        NSString *configPath = nil, *resultPath = nil;
        for (int n = 1; n + 1 < argc; n++) {
            if (strcmp(argv[n], "--config") == 0) configPath = @(argv[++n]);
            else if (strcmp(argv[n], "--result") == 0) resultPath = @(argv[++n]);
        }
        NSDictionary *config = Decode([NSData dataWithContentsOfFile:configPath]);
        if (!config || !ConfigValid(config) || !resultPath) return 64;
        NSBundle *bundle = NSBundle.mainBundle;
        NSString *name = bundle.infoDictionary[@"NativeWorkerIdentifier"];
        NSURL *workerURL = [bundle.bundleURL URLByAppendingPathComponent:@"Contents/XPCServices/DeepTwinWorker.xpc"];
        NSString *requirement = CodeRequirement(workerURL);
        if (!requirement) return 65;
        NSMutableDictionary *report = [@{@"schema": @"native-canary-n0-v1", @"host_pid": @(getpid()),
            @"generation": config[@"generation"], @"expected_worker_requirement": requirement} mutableCopy];
        NSXPCConnection *connection = Connect(name, requirement);
        NSData *hello = Encode(@{@"action": @"hello", @"config": config});
        NSDictionary *greeting = Call(connection, hello);
        if ([bundle.infoDictionary[@"NativeExpectDenied"] boolValue]) {
            report[@"listener_denied"] = @([greeting[@"transport_error"] isKindOfClass:NSNumber.class]);
            report[@"greeting"] = greeting;
        } else if (![greeting[@"ready"] boolValue]) {
            report[@"greeting"] = greeting; report[@"failed_stage"] = @"handshake";
        } else {
            NSMutableArray *before = [NSMutableArray array], *after = [NSMutableArray array];
            for (NSString *key in @[@"tcp4", @"tcp6", @"udp4", @"udp6"])
                [before addObject:SocketProbe(key, [config[@"ports"][key] intValue], @"host-before")];
            [report addEntriesFromDictionary:Call(connection, Encode(@{@"action": @"native", @"config": config}))];
            for (NSString *key in @[@"tcp4", @"tcp6", @"udp4", @"udp6"])
                [after addObject:SocketProbe(key, [config[@"ports"][key] intValue], @"host-after")];
            report[@"positive_before"] = before; report[@"positive_after"] = after;
            NSXPCConnection *wrong = Connect(name, NeverRequirement());
            report[@"wrong_server_rejected"] = @((BOOL)(Call(wrong, hello)[@"transport_error"] != nil));
            [wrong invalidate];
            report[@"malformed_rejected"] = @([Call(connection, [@"{}" dataUsingEncoding:NSUTF8StringEncoding])[@"error"] isEqual:@"invalid_request"]);
            report[@"oversize_rejected"] = @([Call(connection, [NSMutableData dataWithLength:65537])[@"error"] isEqual:@"invalid_request"]);
            NSMutableDictionary *stale = [config mutableCopy]; stale[@"generation"] = @"00000000000000000000000000000000";
            report[@"stale_rejected"] = @([Call(connection, Encode(@{@"action": @"hello", @"config": stale}))[@"error"] isEqual:@"stale_generation"]);
            report[@"unknown_rejected"] = @([Call(connection, Encode(@{@"action": @"arbitrary_shell", @"config": config}))[@"error"] isEqual:@"unknown_action"]);
            report[@"worker_exit_observed"] = @((BOOL)(Call(connection, Encode(@{@"action": @"exit", @"config": config}))[@"transport_error"] != nil));
        }
        [connection invalidate];
        if (![Encode(report) writeToFile:resultPath options:NSDataWritingAtomic error:NULL]) return 74;
    }
    return 0;
}
