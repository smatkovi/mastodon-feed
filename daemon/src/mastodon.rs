//! Mastodon ueber HTTPS -- diesmal ohne Umweg.
//!
//! Die Python-Fassung konnte kein TLS 1.2 (Harmattans OpenSSL ist 0.9.8) und
//! reichte jede Anfrage an ein fremdes Python 3 weiter. rustls kann es
//! selbst, und die Wurzelzertifikate liegen mit im Binary: der Vorrat des
//! Geraets ist von 2011 und kennt die heutigen Aussteller nicht.

use serde_json::Value;
use std::path::Path;
use tokio::io::AsyncWriteExt;

pub type Fehler = Box<dyn std::error::Error + Send + Sync>;

/// Mehr als das holt der Dienst nie von einer einzelnen Datei. Auf 2G ist
/// ein halbes Megabyte eine Minute Warten und ein merklicher Teil des
/// Datenpakets.
pub const BILD_HOECHSTENS: u64 = 512 * 1024;

pub struct Klient {
    http: reqwest::Client,
}

impl Klient {
    pub fn neu() -> Result<Klient, Fehler> {
        let http = reqwest::Client::builder()
            .user_agent("mastodon-feed (Harmattan)")
            // Auf 2G darf eine Antwort dauern; haengen bleiben darf sie nicht,
            // sonst steht der ganze Dienst.
            .timeout(std::time::Duration::from_secs(90))
            .connect_timeout(std::time::Duration::from_secs(30))
            .build()?;
        Ok(Klient { http })
    }

    async fn holen(&self, url: &str, token: Option<&str>) -> Result<Value, Fehler> {
        let mut anfrage = self.http.get(url);
        if let Some(t) = token {
            anfrage = anfrage.bearer_auth(t);
        }
        let antwort = anfrage.send().await?;
        let lage = antwort.status();
        let text = antwort.text().await?;
        if !lage.is_success() {
            // Die Fehlermeldung der Instanz ist brauchbarer als die Nummer
            // allein ("The access token is invalid").
            let grund = serde_json::from_str::<Value>(&text)
                .ok()
                .and_then(|v| v.get("error").and_then(Value::as_str).map(str::to_string))
                .unwrap_or_else(|| text.chars().take(120).collect());
            return Err(format!("{}: {}", lage.as_u16(), grund).into());
        }
        Ok(serde_json::from_str(&text)?)
    }

    pub async fn instanz_titel(&self, host: &str) -> Result<String, Fehler> {
        let daten = self
            .holen(&format!("https://{}/api/v1/instance", host), None)
            .await?;
        Ok(daten
            .get("title")
            .and_then(Value::as_str)
            .unwrap_or(host)
            .to_string())
    }

    pub async fn zeitleiste(
        &self,
        host: &str,
        token: &str,
        seit: &str,
    ) -> Result<Vec<Value>, Fehler> {
        self.liste(
            &format!("https://{}/api/v1/timelines/home?limit=20", host),
            token,
            seit,
        )
        .await
    }

    pub async fn erwaehnungen(
        &self,
        host: &str,
        token: &str,
        seit: &str,
    ) -> Result<Vec<Value>, Fehler> {
        self.liste(
            &format!("https://{}/api/v1/notifications?limit=20", host),
            token,
            seit,
        )
        .await
    }

    async fn liste(&self, url: &str, token: &str, seit: &str) -> Result<Vec<Value>, Fehler> {
        let mut voll = url.to_string();
        if !seit.is_empty() {
            voll.push_str(&format!("&since_id={}", seit));
        }
        match self.holen(&voll, Some(token)).await? {
            Value::Array(a) => Ok(a),
            andere => Err(format!("unerwartete Antwort: {}", andere).into()),
        }
    }

    /// Ein Bild holen -- und beim Hoechstmass abbrechen, statt es erst ganz
    /// zu laden und dann wegzuwerfen.
    pub async fn bild(&self, url: &str, ziel: &Path) -> Result<(), Fehler> {
        let mut antwort = self.http.get(url).send().await?.error_for_status()?;
        if let Some(laenge) = antwort.content_length() {
            if laenge > BILD_HOECHSTENS {
                return Err(format!("{} Bytes, zu gross", laenge).into());
            }
        }
        let neben = ziel.with_extension("teil");
        let mut datei = tokio::fs::File::create(&neben).await?;
        let mut bisher: u64 = 0;
        while let Some(stueck) = antwort.chunk().await? {
            bisher += stueck.len() as u64;
            if bisher > BILD_HOECHSTENS {
                let _ = tokio::fs::remove_file(&neben).await;
                return Err("zu gross".into());
            }
            datei.write_all(&stueck).await?;
        }
        datei.flush().await?;
        drop(datei);
        tokio::fs::rename(&neben, ziel).await?;
        Ok(())
    }
}
