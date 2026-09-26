//! Das Konto und die Schalter -- dieselbe Datei, die auch die
//! Einstellungsseite schreibt: `~/.config/mastodon-feed/account.json`.
//!
//! Zwei Programme schreiben hinein, deshalb wird hier nie die ganze Kopie
//! zurueckgeschrieben: gespeichert werden ausschliesslich die beiden Marken,
//! und zwar in die *frisch* gelesene Datei. Wer die eigene Kopie ganz
//! zurueckschreibt, legt einen Schalter wieder um, den der Nutzer in der
//! Zwischenzeit umgelegt hat -- ein Abruf dauert auf 2G Minuten.

use serde_json::{Map, Value};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

pub fn heim() -> PathBuf {
    // Ein ueber den Sitzungsbus aktivierter Dienst hat HOME; falls doch
    // nicht, ist es auf diesem Geraet immer dasselbe Verzeichnis.
    match std::env::var("HOME") {
        Ok(h) if !h.is_empty() && PathBuf::from(&h).join(".config").is_dir() => PathBuf::from(h),
        _ => PathBuf::from("/home/user"),
    }
}

pub fn verzeichnis() -> PathBuf {
    heim().join(".config").join("mastodon-feed")
}

pub fn pfad() -> PathBuf {
    verzeichnis().join("account.json")
}

pub struct Einstellungen {
    roh: Map<String, Value>,
}

impl Einstellungen {
    pub fn laden() -> Einstellungen {
        let roh = std::fs::read_to_string(pfad())
            .ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok())
            .and_then(|v| match v {
                Value::Object(m) => Some(m),
                _ => None,
            })
            .unwrap_or_default();
        Einstellungen { roh }
    }

    fn zeichen(&self, name: &str) -> String {
        self.roh
            .get(name)
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string()
    }

    fn schalter(&self, name: &str, vorgabe: bool) -> bool {
        self.roh
            .get(name)
            .and_then(Value::as_bool)
            .unwrap_or(vorgabe)
    }

    pub fn instanz(&self) -> String {
        self.zeichen("instance")
    }
    pub fn token(&self) -> String {
        self.zeichen("token")
    }
    pub fn marke_startseite(&self) -> String {
        self.zeichen("last_home")
    }
    pub fn marke_erwaehnungen(&self) -> String {
        self.zeichen("last_notification")
    }

    /// Der Hauptschalter: aus heisst, es wird nichts geholt.
    pub fn an(&self) -> bool {
        self.schalter("enabled", true)
    }
    pub fn startseite(&self) -> bool {
        self.schalter("home", true)
    }
    pub fn erwaehnungen(&self) -> bool {
        self.schalter("mentions", true)
    }
    pub fn avatare(&self) -> bool {
        self.schalter("avatars", true)
    }
    pub fn bilder(&self) -> bool {
        self.schalter("images", true)
    }

    pub fn eingerichtet(&self) -> bool {
        !self.instanz().is_empty() && !self.token().is_empty()
    }

    /// Sekunden zwischen zwei Abrufen, nie unter zwei Minuten.
    pub fn intervall(&self) -> u64 {
        let wert = self
            .roh
            .get("interval")
            .and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64)))
            .unwrap_or(600);
        wert.max(120) as u64
    }
}

/// Nur die beiden Marken sichern, alles andere bleibt, wie es auf der Platte
/// steht. Geschrieben wird ueber eine Nebendatei mit Modus 0600 und dann
/// umbenannt: in der Datei steht ein Zugangstoken, und ein halb geschriebenes
/// JSON waere schlimmer als gar keines.
pub fn marken_sichern(startseite: &str, erwaehnungen: &str) -> std::io::Result<()> {
    let dir = verzeichnis();
    std::fs::create_dir_all(&dir)?;
    let mut roh = Einstellungen::laden().roh;
    roh.insert("last_home".into(), Value::String(startseite.to_string()));
    roh.insert(
        "last_notification".into(),
        Value::String(erwaehnungen.to_string()),
    );
    let text = serde_json::to_string_pretty(&Value::Object(roh))?;
    let neben = dir.join("account.json.new");
    {
        let mut datei = std::fs::File::create(&neben)?;
        datei.write_all(text.as_bytes())?;
        datei.write_all(b"\n")?;
        datei.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    std::fs::rename(&neben, pfad())
}
