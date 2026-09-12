#import "Checks.h"

int main(void) {
    @autoreleasepool {
        alarm(8);
        NSData *input = [[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile];
        NSDictionary *config = Decode(input);
        if (!ConfigValid(config)) return 64;
        NSData *output = Encode(RunChecks(config, @"child"));
        [[NSFileHandle fileHandleWithStandardOutput] writeData:output];
    }
    return 0;
}
