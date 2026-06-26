## ADDED Requirements

### Requirement: Produce an Apple Silicon application bundle

The release process SHALL produce a reproducible arm64 macOS application bundle and installer image containing the desktop frontend, Tauri host, and compatible YAACLI Python sidecar.

#### Scenario: Release build completes

- **WHEN** the release workflow runs from a supported tagged source revision with required signing inputs
- **THEN** it produces versioned arm64 application and installer artifacts whose embedded components report compatible versions

### Requirement: Run without a system Python installation

The packaged application MUST provide all Python runtime components required for the bundled YAACLI sidecar and MUST NOT depend on Homebrew, `uv`, or a user-installed Python interpreter.

#### Scenario: Application starts on a clean supported Mac

- **WHEN** the application is installed on a supported Apple Silicon Mac without development tooling
- **THEN** it starts the bundled sidecar and can complete the protocol handshake

### Requirement: Use macOS security and storage facilities

The packaged application SHALL request only declared Tauri capabilities, SHALL store provider secrets in macOS Keychain, and SHALL store application data under an application-specific user data directory.

#### Scenario: Provider credential is saved

- **WHEN** the user saves a provider credential through desktop settings
- **THEN** the secret is written to Keychain and configuration files contain only non-secret metadata or references

### Requirement: Sign and notarize release artifacts

Public release artifacts MUST be code signed and notarized using configured Apple Developer credentials before publication.

#### Scenario: Signing or notarization fails

- **WHEN** the release workflow cannot complete signing or notarization
- **THEN** it fails the release and does not publish the affected artifact as a production download

### Requirement: Update application components atomically

The update mechanism SHALL verify signed update metadata and SHALL update the Tauri application and bundled sidecar as one compatible application version.

#### Scenario: Valid update is installed

- **WHEN** the user accepts an available update with valid signature metadata
- **THEN** the updater replaces the application bundle and the next launch negotiates the protocol with the sidecar bundled in that same version

#### Scenario: Update verification fails

- **WHEN** update metadata or payload signature verification fails
- **THEN** the installed application remains unchanged and the user receives a non-sensitive failure message
