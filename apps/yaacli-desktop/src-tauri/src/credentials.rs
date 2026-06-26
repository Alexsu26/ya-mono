use serde::Serialize;

const KEYCHAIN_SERVICE: &str = "com.wh1isper.yaacli.desktop";
const PROVIDER_ENV: &[(&str, &str)] = &[
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
    ("deepseek", "DEEPSEEK_API_KEY"),
    ("zai", "ZAI_API_KEY"),
    ("gemini", "GEMINI_API_KEY"),
];

#[derive(Serialize)]
pub struct CredentialState {
    provider: String,
    present: bool,
}

fn validate_provider(provider: &str) -> Result<(), String> {
    if provider.is_empty()
        || provider.len() > 64
        || !provider.chars().all(|character| {
            character.is_ascii_alphanumeric() || matches!(character, '-' | '_' | '.')
        })
    {
        return Err("provider must use 1-64 letters, numbers, dots, dashes, or underscores".into());
    }
    Ok(())
}

#[cfg(target_os = "macos")]
fn credential_exists(provider: &str) -> bool {
    security_framework::passwords::get_generic_password(KEYCHAIN_SERVICE, provider).is_ok()
}

#[cfg(target_os = "macos")]
pub fn inject_provider_environment(command: &mut tokio::process::Command) {
    for (provider, variable) in PROVIDER_ENV {
        if let Ok(secret_bytes) =
            security_framework::passwords::get_generic_password(KEYCHAIN_SERVICE, provider)
        {
            if let Ok(secret) = String::from_utf8(secret_bytes) {
                command.env(variable, secret);
            }
        }
    }
}

#[cfg(not(target_os = "macos"))]
pub fn inject_provider_environment(_command: &mut tokio::process::Command) {}

#[cfg(not(target_os = "macos"))]
fn credential_exists(_provider: &str) -> bool {
    false
}

#[tauri::command]
pub async fn credential_status(provider: String) -> Result<CredentialState, String> {
    validate_provider(&provider)?;
    Ok(CredentialState {
        present: credential_exists(&provider),
        provider,
    })
}

#[tauri::command]
pub async fn credential_set(provider: String, secret: String) -> Result<CredentialState, String> {
    validate_provider(&provider)?;
    if secret.is_empty() || secret.len() > 16 * 1024 {
        return Err("credential must contain between 1 and 16384 characters".into());
    }
    #[cfg(target_os = "macos")]
    security_framework::passwords::set_generic_password(
        KEYCHAIN_SERVICE,
        &provider,
        secret.as_bytes(),
    )
    .map_err(|error| format!("could not store credential in macOS Keychain: {error}"))?;
    #[cfg(not(target_os = "macos"))]
    return Err("credential storage is available only on macOS".into());

    Ok(CredentialState {
        provider,
        present: true,
    })
}

#[tauri::command]
pub async fn credential_delete(provider: String) -> Result<CredentialState, String> {
    validate_provider(&provider)?;
    #[cfg(target_os = "macos")]
    if credential_exists(&provider) {
        security_framework::passwords::delete_generic_password(KEYCHAIN_SERVICE, &provider)
            .map_err(|error| format!("could not delete credential from macOS Keychain: {error}"))?;
    }
    #[cfg(not(target_os = "macos"))]
    return Err("credential storage is available only on macOS".into());

    Ok(CredentialState {
        provider,
        present: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_names_are_bounded_before_keychain_access() {
        assert!(validate_provider("openai").is_ok());
        assert!(validate_provider("oauth.codex").is_ok());
        assert!(validate_provider("").is_err());
        assert!(validate_provider("bad/provider").is_err());
        assert!(PROVIDER_ENV.contains(&("zai", "ZAI_API_KEY")));
    }
}
