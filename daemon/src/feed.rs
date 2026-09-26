//! Die Ereignisansicht: `com.nokia.home.EventFeed` auf dem Sitzungsbus.
//!
//! `addItem` antwortet **-1 und sagt sonst nichts**, wenn ein einziger
//! Schluessel im Dictionary fehlt oder den falschen Typ hat. Nichts erscheint
//! im Feed, nirgends eine Fehlermeldung. Der vollstaendige Satz unten ist
//! deshalb keine Zierde, und die Typen sind genau die der Python-Fassung:
//! der Zeitstempel als Zeichenkette, `video` als Wahrheitswert, `imageList`
//! als Feld von Zeichenketten.

use std::collections::HashMap;
use zbus::zvariant::Value as DV;

pub const BUSNAME: &str = "org.smatkovi.MastodonFeed";
const DIENST: &str = "com.nokia.home.EventFeed";
const PFAD: &str = "/eventfeed";

const SITZUNGSBUS_DATEI: &str = "/tmp/session_bus_address.user";

pub type Fehler = Box<dyn std::error::Error + Send + Sync>;

/// Harmattan schreibt die Adresse des Sitzungsbusses in diese Datei.
///
/// Ein ueber den Bus aktivierter Dienst bekommt sie zwar in der Umgebung,
/// aber nicht jeder Start kommt von dort -- und die Adresse wechselt mit der
/// Sitzung, also jedes Mal frisch lesen.
pub fn sitzungsbus_adresse() -> Option<String> {
    if let Ok(a) = std::env::var("DBUS_SESSION_BUS_ADDRESS") {
        if !a.is_empty() {
            return Some(a);
        }
    }
    let inhalt = std::fs::read_to_string(SITZUNGSBUS_DATEI).ok()?;
    for zeile in inhalt.lines() {
        if let Some(rest) = zeile.split_once("DBUS_SESSION_BUS_ADDRESS=") {
            let mut wert = rest.1.trim().trim_end_matches(';').to_string();
            if wert.len() > 1 {
                let erstes = wert.chars().next().unwrap();
                if (erstes == '"' || erstes == '\'') && wert.ends_with(erstes) {
                    wert = wert[1..wert.len() - 1].to_string();
                }
            }
            if !wert.is_empty() {
                return Some(wert);
            }
        }
    }
    None
}

pub async fn verbinden() -> Result<zbus::Connection, Fehler> {
    let adresse = sitzungsbus_adresse().ok_or("kein Sitzungsbus -- steht die Oberflaeche schon?")?;
    Ok(zbus::connection::Builder::address(adresse.as_str())?
        .build()
        .await?)
}

/// True, wenn dieser Prozess der Dienst ist; false, wenn schon einer laeuft.
///
/// Der Umweg ueber den Sitzungsbus ist nicht Geschmackssache: ein
/// Upstart-Job unter /etc/init/apps laeuft als uid 0 mit leerem Rechtesatz
/// und kann die Kennung nicht wechseln -- aegis-exec landet dort auf nobody,
/// su scheitert an "can't set groups", und weder nobody noch dieser root darf
/// das Konto lesen. Ein ueber den Sitzungsbus aktivierter Dienst dagegen
/// laeuft als Besitzer des Busses, also als "user", mit HOME und Zugriff
/// darauf.
pub async fn namen_beanspruchen(bus: &zbus::Connection) -> Result<bool, Fehler> {
    let antwort = bus
        .request_name_with_flags(
            BUSNAME,
            zbus::fdo::RequestNameFlags::DoNotQueue.into(),
        )
        .await?;
    Ok(matches!(
        antwort,
        zbus::fdo::RequestNameReply::PrimaryOwner
    ))
}

pub struct Eintrag {
    pub symbol: String,
    pub titel: String,
    pub text: String,
    pub fusszeile: String,
    pub zeitstempel: String,
    pub bilder: Vec<String>,
    pub video: bool,
    /// Die Adresse, die beim Tippen geoeffnet wird; leer heisst, der Eintrag
    /// reagiert nicht.
    pub ziel: String,
}

pub struct Ereignisansicht<'a> {
    proxy: zbus::Proxy<'a>,
}

impl<'a> Ereignisansicht<'a> {
    pub async fn neu(bus: &zbus::Connection) -> Result<Ereignisansicht<'a>, Fehler> {
        let proxy = zbus::Proxy::new(bus, DIENST, PFAD, DIENST).await?;
        Ok(Ereignisansicht { proxy })
    }

    pub async fn eintragen(&self, e: &Eintrag, quelle: &str, anzeige: &str) -> Result<i64, Fehler> {
        let mut d: HashMap<&str, DV> = HashMap::new();
        d.insert("icon", DV::from(e.symbol.as_str()));
        d.insert("title", DV::from(e.titel.as_str()));
        d.insert("body", DV::from(e.text.as_str()));
        d.insert("imageList", DV::from(e.bilder.clone()));
        d.insert("timestamp", DV::from(e.zeitstempel.as_str()));
        d.insert("footer", DV::from(e.fusszeile.as_str()));
        d.insert("video", DV::from(e.video));
        d.insert("action", DV::from(e.ziel.as_str()));
        d.insert("sourceName", DV::from(quelle));
        d.insert("sourceDisplayName", DV::from(anzeige));
        let kennung: i64 = self.proxy.call("addItem", &(d,)).await?;
        Ok(kennung)
    }
}
