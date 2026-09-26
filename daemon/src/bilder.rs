//! Profilbilder und Vorschaubilder -- mit Budget, Obergrenze und einem
//! Zwischenspeicher, der nicht waechst.
//!
//! Das Geraet haengt oft auf 2G, und /home/user ist eine kleine Partition.
//! Beides zusammen heisst: hoechstens so viele neue Bilder je Abruf, jedes
//! hoechstens ein halbes Megabyte, und der Vorrat wird gekappt.

use crate::mastodon::Klient;
use std::path::{Path, PathBuf};

/// Was ein Abruf an neuen Bildern holen darf. Was darueber hinausgeht,
/// erscheint einfach ohne Bild -- der Text ist die Hauptsache.
pub const JE_ABRUF: u32 = 20;
/// Wieviel Platz die Bilder behalten duerfen.
pub const VORRAT_BYTES: u64 = 6 * 1024 * 1024;

const ENDUNGEN: &[&str] = &[".png", ".jpg", ".jpeg", ".gif", ".webp"];

pub fn verzeichnis() -> PathBuf {
    crate::einstellungen::heim()
        .join(".cache")
        .join("mastodon-feed")
}

/// Ein gleichbleibender Dateiname je Adresse (FNV-1a, 64 Bit). Kein md5
/// dafuer ins Binary holen; gebraucht wird nur, dass derselbe Link immer
/// denselben Namen ergibt.
fn name_fuer(url: &str) -> String {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for b in url.as_bytes() {
        hash ^= *b as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    let ohne_frage = url.split('?').next().unwrap_or("").to_lowercase();
    let endung = ENDUNGEN
        .iter()
        .find(|e| ohne_frage.ends_with(**e))
        .copied()
        .unwrap_or(".jpg");
    format!("{:016x}{}", hash, endung)
}

pub struct Budget<'a> {
    pub rest: u32,
    klient: &'a Klient,
}

impl<'a> Budget<'a> {
    pub fn neu(klient: &'a Klient, rest: u32) -> Budget<'a> {
        Budget { rest, klient }
    }

    /// Der Pfad zum Bild hinter der Adresse, notfalls "".
    ///
    /// Ein Bild, das schon da ist, kostet nichts und zaehlt nicht gegen das
    /// Budget -- nur neue tun das.
    pub async fn bild(&mut self, url: &str) -> String {
        if url.is_empty() {
            return String::new();
        }
        let ziel = verzeichnis().join(name_fuer(url));
        if ziel.exists() {
            // Anfassen, damit noch Gebrauchtes nicht als Aeltestes wegfaellt.
            let _ = anfassen(&ziel);
            return ziel.to_string_lossy().into_owned();
        }
        if self.rest == 0 {
            return String::new();
        }
        self.rest -= 1;
        if std::fs::create_dir_all(verzeichnis()).is_err() {
            return String::new();
        }
        match self.klient.bild(url, &ziel).await {
            Ok(()) => ziel.to_string_lossy().into_owned(),
            Err(e) => {
                crate::melden(&format!("Bild: {}", crate::kette(e.as_ref())));
                String::new()
            }
        }
    }
}

fn anfassen(pfad: &Path) -> std::io::Result<()> {
    let jetzt = std::time::SystemTime::now();
    std::fs::File::open(pfad)?.set_times(
        std::fs::FileTimes::new()
            .set_accessed(jetzt)
            .set_modified(jetzt),
    )
}

/// Die aeltesten Bilder wegwerfen, sobald der Vorrat zu gross wird.
pub fn kappen() {
    let mut dateien: Vec<(std::time::SystemTime, u64, PathBuf)> = Vec::new();
    let mut gesamt: u64 = 0;
    let eintraege = match std::fs::read_dir(verzeichnis()) {
        Ok(e) => e,
        Err(_) => return,
    };
    for eintrag in eintraege.flatten() {
        if let Ok(daten) = eintrag.metadata() {
            if daten.is_file() {
                let wann = daten.modified().unwrap_or(std::time::UNIX_EPOCH);
                gesamt += daten.len();
                dateien.push((wann, daten.len(), eintrag.path()));
            }
        }
    }
    dateien.sort_by_key(|(wann, _, _)| *wann);
    for (_, groesse, pfad) in dateien {
        if gesamt <= VORRAT_BYTES {
            break;
        }
        if std::fs::remove_file(&pfad).is_ok() {
            gesamt -= groesse;
        }
    }
}
