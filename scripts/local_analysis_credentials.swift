import Darwin
import Foundation
import LocalAuthentication
import Security

private let credentialService = "com.jobradarcoach.local-analysis"
private let credentialAccount = "pgpassword"
private let credentialLabel = "Job Radar Coach local analysis database password"
private let maximumCredentialBytes = 16_384

private enum CredentialFailure: Error, Equatable {
    case missing
    case lockedOrAccessDenied
    case unavailable
    case invalid
    case provisionFailed

    var category: String {
        switch self {
        case .missing:
            return "missing"
        case .lockedOrAccessDenied:
            return "locked_or_access_denied"
        case .unavailable:
            return "unavailable"
        case .invalid:
            return "invalid"
        case .provisionFailed:
            return "provision_failed"
        }
    }
}

private protocol CredentialStore {
    func load() throws -> Data
    func save(_ secret: Data) throws
}

private struct KeychainCredentialStore: CredentialStore {
    let keychain: SecKeychain
    let service: String
    let account: String
    let label: String

    static func systemDefault() throws -> KeychainCredentialStore {
        var keychain: SecKeychain?
        guard SecKeychainCopyDefault(&keychain) == errSecSuccess,
              let keychain else {
            throw CredentialFailure.unavailable
        }
        return KeychainCredentialStore(
            keychain: keychain,
            service: credentialService,
            account: credentialAccount,
            label: credentialLabel
        )
    }

    private var identity: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    private var match: [String: Any] {
        var query = identity
        query[kSecMatchSearchList as String] = [keychain]
        return query
    }

    private func nonInteractiveContext() -> LAContext {
        let context = LAContext()
        context.interactionNotAllowed = true
        return context
    }

    func load() throws -> Data {
        var interactionWasAllowed = DarwinBoolean(false)
        guard SecKeychainGetUserInteractionAllowed(&interactionWasAllowed) == errSecSuccess,
              SecKeychainSetUserInteractionAllowed(false) == errSecSuccess else {
            throw CredentialFailure.unavailable
        }
        defer {
            _ = SecKeychainSetUserInteractionAllowed(interactionWasAllowed.boolValue)
        }

        var keychainStatus: SecKeychainStatus = 0
        guard SecKeychainGetStatus(keychain, &keychainStatus) == errSecSuccess else {
            throw CredentialFailure.unavailable
        }
        guard keychainStatus & UInt32(kSecUnlockStateStatus) != 0 else {
            throw CredentialFailure.lockedOrAccessDenied
        }

        var query = match
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        query[kSecUseAuthenticationContext as String] = nonInteractiveContext()
        query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail

        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data else {
                throw CredentialFailure.invalid
            }
            return data
        case errSecItemNotFound:
            throw CredentialFailure.missing
        case errSecInteractionNotAllowed, errSecAuthFailed, errSecNotAvailable,
             errSecUserCanceled:
            throw CredentialFailure.lockedOrAccessDenied
        default:
            throw CredentialFailure.unavailable
        }
    }

    func save(_ secret: Data) throws {
        var access: SecAccess?
        guard SecAccessCreate(label as CFString, nil, &access) == errSecSuccess,
              let access else {
            throw CredentialFailure.provisionFailed
        }

        var item = identity
        item[kSecValueData as String] = secret
        item[kSecAttrLabel as String] = label
        item[kSecAttrAccess as String] = access
        item[kSecUseKeychain as String] = keychain
        let status = SecItemAdd(item as CFDictionary, nil)
        if status != errSecSuccess {
            throw CredentialFailure.provisionFailed
        }
    }
}

private struct RunRequest {
    let command: [String]
    let password: String
}

private func validatedSecret(_ data: Data) throws -> Data {
    guard !data.isEmpty,
          data.count <= maximumCredentialBytes,
          !data.contains(0),
          String(data: data, encoding: .utf8) != nil else {
        throw CredentialFailure.invalid
    }
    return data
}

private func provision(_ input: Data, store: CredentialStore) throws {
    try store.save(validatedSecret(input))
}

private func prepareRun(_ arguments: [String], store: CredentialStore) throws -> RunRequest {
    guard arguments.count >= 2,
          arguments[0] == "--",
          arguments[1].hasPrefix("/") else {
        throw CredentialFailure.invalid
    }
    let secret = try validatedSecret(store.load())
    guard let password = String(data: secret, encoding: .utf8) else {
        throw CredentialFailure.invalid
    }
    return RunRequest(command: Array(arguments.dropFirst()), password: password)
}

private func replaceProcess(with request: RunRequest) -> Never {
    guard setenv("PGPASSWORD", request.password, 1) == 0 else {
        FileHandle.standardError.write(Data("credential_error:unavailable\n".utf8))
        exit(70)
    }

    let pointers = request.command.map { strdup($0) } + [nil]
    defer {
        for pointer in pointers where pointer != nil {
            free(pointer)
        }
    }
    pointers.withUnsafeBufferPointer { buffer in
        execv(request.command[0], UnsafeMutablePointer(mutating: buffer.baseAddress))
    }
    unsetenv("PGPASSWORD")
    FileHandle.standardError.write(Data("credential_error:exec_failed\n".utf8))
    exit(71)
}

private func fail(_ failure: CredentialFailure) -> Never {
    FileHandle.standardError.write(Data("credential_error:\(failure.category)\n".utf8))
    switch failure {
    case .missing:
        exit(66)
    case .lockedOrAccessDenied:
        exit(77)
    case .invalid:
        exit(64)
    case .unavailable, .provisionFailed:
        exit(69)
    }
}

private func runMain(arguments: [String]) -> Never {
    do {
        let store = try KeychainCredentialStore.systemDefault()
        guard let operation = arguments.first else {
            fail(.invalid)
        }
        switch operation {
        case "provision":
            guard arguments.count == 1 else {
                fail(.invalid)
            }
            let secret = FileHandle.standardInput.readDataToEndOfFile()
            try provision(secret, store: store)
            FileHandle.standardOutput.write(Data("credential_provisioned\n".utf8))
            exit(0)
        case "run":
            replaceProcess(with: try prepareRun(Array(arguments.dropFirst()), store: store))
        default:
            fail(.invalid)
        }
    } catch let failure as CredentialFailure {
        fail(failure)
    } catch {
        fail(.unavailable)
    }
}

#if TESTING
private final class FakeStore: CredentialStore {
    var loaded: Result<Data, CredentialFailure>
    var saved: Data?

    init(loaded: Result<Data, CredentialFailure>) {
        self.loaded = loaded
    }

    func load() throws -> Data {
        try loaded.get()
    }

    func save(_ secret: Data) throws {
        saved = secret
    }
}

private struct SelfTestFailure: Error {
    let name: String
}

private func require(_ condition: @autoclosure () -> Bool, _ name: String) throws {
    guard condition() else {
        throw SelfTestFailure(name: name)
    }
}

private func addRestrictedFixture(
    to keychain: SecKeychain,
    service: String,
    label: String,
    account: String,
    secret: Data,
    trustedApplicationPath: String
) -> OSStatus {
    var trustedApplication: SecTrustedApplication?
    let trustedStatus = trustedApplicationPath.withCString {
        SecTrustedApplicationCreateFromPath($0, &trustedApplication)
    }
    guard trustedStatus == errSecSuccess, let trustedApplication else {
        return trustedStatus
    }
    var access: SecAccess?
    let accessStatus = SecAccessCreate(
        label as CFString,
        [trustedApplication] as CFArray,
        &access
    )
    guard accessStatus == errSecSuccess, let access else {
        return accessStatus
    }
    let item: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: service,
        kSecAttrAccount as String: account,
        kSecValueData as String: secret,
        kSecAttrAccess as String: access,
        kSecUseKeychain as String: keychain,
    ]
    return SecItemAdd(item as CFDictionary, nil)
}

private func executeSelfTests() throws {
    let syntheticSecret = Data("synthetic-password-never-print".utf8)

    let fake = FakeStore(loaded: .success(syntheticSecret))
    try provision(syntheticSecret, store: fake)
    try require(fake.saved == syntheticSecret, "stdin_provisioning")
    let request = try prepareRun(["--", "/usr/bin/true", "safe-arg"], store: fake)
    try require(request.command == ["/usr/bin/true", "safe-arg"], "child_argv")
    try require(
        request.password == String(data: syntheticSecret, encoding: .utf8),
        "child_env"
    )
    try require(!request.command.joined().contains("synthetic-password"), "argv_leak")

    let missingFake = FakeStore(loaded: .failure(.missing))
    do {
        _ = try prepareRun(["--", "/usr/bin/true"], store: missingFake)
        throw SelfTestFailure(name: "missing_category")
    } catch let failure as CredentialFailure {
        try require(failure == .missing, "missing_category")
    }

    guard let testRoot = ProcessInfo.processInfo.environment["JRC_CREDENTIAL_TEST_ROOT"],
          testRoot.hasPrefix("/") else {
        throw SelfTestFailure(name: "explicit_test_root")
    }
    let temporaryDirectory = URL(fileURLWithPath: testRoot, isDirectory: true)
        .appendingPathComponent("jrc-credential-self-test-\(UUID().uuidString)", isDirectory: true)
    let keychainURL = temporaryDirectory.appendingPathComponent("synthetic.keychain-db")
    try FileManager.default.createDirectory(
        at: temporaryDirectory,
        withIntermediateDirectories: false,
        attributes: [.posixPermissions: 0o700]
    )
    defer {
        try? FileManager.default.removeItem(at: temporaryDirectory)
    }

    var interactionWasAllowed = DarwinBoolean(false)
    try require(
        SecKeychainGetUserInteractionAllowed(&interactionWasAllowed) == errSecSuccess,
        "read_interaction_policy"
    )
    try require(
        SecKeychainSetUserInteractionAllowed(false) == errSecSuccess,
        "disable_all_keychain_ui"
    )
    defer {
        _ = SecKeychainSetUserInteractionAllowed(interactionWasAllowed.boolValue)
    }

    let testID = UUID().uuidString
    let testService = "com.jobradarcoach.local-analysis.TEST-ONLY.\(testID)"
    let testLabel = "TEST ONLY disposable Job Radar Coach credential \(testID)"
    let keychainPassword = Array("synthetic-keychain-password".utf8)
    var keychain: SecKeychain?
    let createStatus = keychainURL.path.withCString { path in
        keychainPassword.withUnsafeBytes { password in
            SecKeychainCreate(
                path,
                UInt32(keychainPassword.count),
                password.baseAddress,
                false,
                nil,
                &keychain
            )
        }
    }
    try require(createStatus == errSecSuccess && keychain != nil, "temporary_keychain_create")
    guard let keychain else {
        throw SelfTestFailure(name: "temporary_keychain_create")
    }
    defer {
        SecKeychainDelete(keychain)
    }

    let store = KeychainCredentialStore(
        keychain: keychain,
        service: testService,
        account: credentialAccount,
        label: testLabel
    )
    try store.save(syntheticSecret)
    let loaded = try store.load()
    try require(loaded == syntheticSecret, "native_success")

    let missingStore = KeychainCredentialStore(
        keychain: keychain,
        service: testService,
        account: "missing-fixture",
        label: testLabel
    )
    do {
        _ = try missingStore.load()
        throw SelfTestFailure(name: "native_missing_no_ui")
    } catch let failure as CredentialFailure {
        try require(failure == .missing, "native_missing_no_ui")
    }

    try require(SecKeychainLock(keychain) == errSecSuccess, "temporary_keychain_lock")
    let lockedStart = Date()
    do {
        _ = try store.load()
        throw SelfTestFailure(name: "native_locked_no_ui")
    } catch let failure as CredentialFailure {
        try require(failure == .lockedOrAccessDenied, "native_locked_no_ui")
    }
    try require(Date().timeIntervalSince(lockedStart) < 2, "native_locked_bounded")

    let unlockStatus = keychainPassword.withUnsafeBytes { password in
        SecKeychainUnlock(keychain, UInt32(keychainPassword.count), password.baseAddress, true)
    }
    try require(unlockStatus == errSecSuccess, "temporary_keychain_unlock")

    let deniedAccount = "acl-denied-fixture"
    try require(
        addRestrictedFixture(
            to: keychain,
            service: testService,
            label: testLabel,
            account: deniedAccount,
            secret: syntheticSecret,
            trustedApplicationPath: "/usr/bin/false"
        ) == errSecSuccess,
        "acl_fixture"
    )
    let deniedStore = KeychainCredentialStore(
        keychain: keychain,
        service: testService,
        account: deniedAccount,
        label: testLabel
    )
    let deniedStart = Date()
    do {
        _ = try deniedStore.load()
        throw SelfTestFailure(name: "native_acl_denied_no_ui")
    } catch let failure as CredentialFailure {
        try require(failure == .lockedOrAccessDenied, "native_acl_denied_no_ui")
    }
    try require(Date().timeIntervalSince(deniedStart) < 5, "native_acl_bounded")
}

private func runSelfTests() -> Int32 {
    do {
        try executeSelfTests()
        FileHandle.standardOutput.write(
            Data("SELF_TEST_OK synthetic_flow native_success native_missing_no_ui native_locked_no_ui native_acl_denied_no_ui\n".utf8)
        )
        return 0
    } catch let failure as SelfTestFailure {
        FileHandle.standardError.write(Data("self_test_failed:\(failure.name)\n".utf8))
        return 1
    } catch let failure as CredentialFailure {
        FileHandle.standardError.write(
            Data("self_test_failed:credential_\(failure.category)\n".utf8)
        )
        return 1
    } catch {
        FileHandle.standardError.write(Data("self_test_failed:unexpected\n".utf8))
        return 1
    }
}

let selfTestExit = runSelfTests()
exit(selfTestExit)
#else
runMain(arguments: Array(CommandLine.arguments.dropFirst()))
#endif
