//! Mastodon in der Ereignisansicht des N9/N950 -- der Dienst.
//!
//! Die Vorgaenger-Fassung war Python 2 und musste fuer jede HTTPS-Anfrage ein
//! fremdes Python 3 aufrufen, weil Harmattans OpenSSL 0.9.8 kein TLS 1.2
//! kann. Hier faellt beides weg: rustls spricht TLS selbst, und das Binary
//! ist statisch gegen musl gebunden, also ist die glibc 2.10 des Geraets
//! gleichgueltig.
//!
//! Gestartet wird der Dienst ueber den *Sitzungs*-D-Bus und laeuft dadurch
//! als "user" -- der Upstart-Job unter /etc/init/apps stoesst ihn nur an. Die
//! Begruendung steht in feed.rs.

mod bilder;
mod einstellungen;
mod feed;
mod mastodon;
mod text;

use einstellungen::Einstellungen;
use serde_json::Value;
use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};

const QUELLE: &str = "mastodon-feed";
const ANZEIGE: &str = "Mastodon";
const SYMBOL: &str = "icon-m-content-description";

/// In den Probe-Betriebsarten soll die Meldung auch auf dem Schirm stehen.
static AUCH_AUF_DEM_SCHIRM: AtomicBool = AtomicBool::new(false);

/// Eigenes Log statt einer Umleitung im Upstart-Job: als D-Bus-Dienst
/// richtet die niemand ein, und /var/log gehoert root -- wir laufen als
/// "user". Das Log liegt deshalb neben dem Konto und wird gekappt, bevor es
/// die kleine Home-Partition fuellt.
pub fn melden(text: &str) {
    let zeile = format!(
        "{} {}\n",
        chrono::Local::now().format("%H:%M:%S"),
        text
    );
    if AUCH_AUF_DEM_SCHIRM.load(Ordering::Relaxed) {
        print!("{}", zeile);
        let _ = std::io::stdout().flush();
    }
    let pfad = einstellungen::verzeichnis().join("feedd.log");
    let _ = std::fs::create_dir_all(einstellungen::verzeichnis());
    if let Ok(daten) = std::fs::metadata(&pfad) {
        if daten.len() > 256 * 1024 {
            let _ = std::fs::rename(&pfad, pfad.with_extension("log.1"));
        }
    }
    if let Ok(mut datei) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&pfad)
    {
        let _ = datei.write_all(zeile.as_bytes());
    }
}

/// Ein Fehler samt seiner Ursache.
///
/// reqwest sagt von sich aus nur "error sending request for url (...)" -- der
/// Grund (Namensaufloesung, Zeitueberschreitung, Zertifikat) steckt erst in
/// der Ursachenkette. Auf einem Geraet, dessen einziges Fenster nach innen
/// dieses Log ist, ist das der Unterschied zwischen einer Diagnose und einem
/// Achselzucken.
pub fn kette(fehler: &(dyn std::error::Error + 'static)) -> String {
    let mut text = fehler.to_string();
    let mut ursache = fehler.source();
    while let Some(u) = ursache {
        text.push_str(": ");
        text.push_str(&u.to_string());
        ursache = u.source();
    }
    text
}

/// Die eigene Kennung -- ohne libc, aus /proc.
fn eigene_uid() -> String {
    std::fs::read_to_string("/proc/self/status")
        .ok()
        .and_then(|t| {
            t.lines()
                .find(|z| z.starts_with("Uid:"))
                .and_then(|z| z.split_whitespace().nth(1).map(str::to_string))
        })
        .unwrap_or_else(|| "?".into())
}

/// Der eigene Pfad und die laufende Fassung, als (Geraet, Inode).
///
/// Damit erkennt der Dienst, dass er abgeloest wurde: dpkg legt die neue
/// Datei daneben und benennt sie um, also zeigt derselbe Pfad danach auf
/// einen anderen Inode -- waehrend `/proc/self/exe` weiter auf den alten
/// zeigt, auch wenn der schon geloescht ist.
///
/// Noetig ist das, weil ein Update den laufenden Dienst sonst gar nicht
/// erreicht: der Upstart-Job startet ihn ja nicht, er sieht nur nach, ob
/// jemand den Bus-Namen haelt -- und aus dem postinst heraus laesst aegis
/// kein kill zu ("Operation not permitted"), waehrend dasselbe kill per sudo
/// durchgeht.
fn eigener_stand() -> Option<(u64, u64)> {
    use std::os::unix::fs::MetadataExt;
    let daten = std::fs::metadata("/proc/self/exe").ok()?;
    Some((daten.dev(), daten.ino()))
}

fn eigener_pfad() -> std::path::PathBuf {
    let pfad = std::env::current_exe().unwrap_or_default();
    // Ist die Datei schon ersetzt, haengt Linux " (deleted)" an.
    let text = pfad.to_string_lossy();
    match text.strip_suffix(" (deleted)") {
        Some(ohne) => std::path::PathBuf::from(ohne),
        None => pfad.clone(),
    }
}

fn abgeloest(start: Option<(u64, u64)>) -> bool {
    use std::os::unix::fs::MetadataExt;
    let start = match start {
        Some(s) => s,
        None => return false,
    };
    match std::fs::metadata(eigener_pfad()) {
        Ok(d) => (d.dev(), d.ino()) != start,
        // Weg ist auch eine Aenderung: dann wurde das Paket entfernt.
        Err(_) => true,
    }
}

fn kennung(status: &Value) -> String {
    match status.get("id") {
        Some(Value::String(s)) => s.clone(),
        Some(Value::Number(n)) => n.to_string(),
        _ => String::new(),
    }
}

fn zeichen(wert: Option<&Value>) -> &str {
    wert.and_then(Value::as_str).unwrap_or("")
}

/// Ein Beitrag wird ein Eintrag.
async fn eintrag_bauen(
    status: &Value,
    fusszeile: &str,
    budget: &mut bilder::Budget<'_>,
    cfg: &Einstellungen,
) -> feed::Eintrag {
    let konto = status.get("account").cloned().unwrap_or(Value::Null);
    let mut wer = {
        let name = zeichen(konto.get("display_name"));
        if name.is_empty() {
            let acct = zeichen(konto.get("acct"));
            if acct.is_empty() { "?".to_string() } else { acct.to_string() }
        } else {
            name.to_string()
        }
    };
    let mut inhalt = text::klartext(zeichen(status.get("content")));
    // Bei einem geteilten Beitrag zaehlt der geteilte: sein Text wird
    // angezeigt, seine Bilder, sein Link.
    let gezeigt = match status.get("reblog") {
        Some(innen) if !innen.is_null() => {
            let acct = zeichen(innen.get("account").and_then(|a| a.get("acct")));
            wer = format!("{} \u{21bb} {}", wer, if acct.is_empty() { "?" } else { acct });
            inhalt = text::klartext(zeichen(innen.get("content")));
            innen.clone()
        }
        _ => status.clone(),
    };
    if inhalt.is_empty() {
        inhalt = "(kein Text)".to_string();
    }

    let mut symbol = SYMBOL.to_string();
    if cfg.avatare() {
        // avatar_static, nicht avatar: ein bewegtes GIF waere ein viel
        // groesserer Download, und der Feed zeigt ohnehin ein Standbild.
        let mut adresse = zeichen(konto.get("avatar_static"));
        if adresse.is_empty() {
            adresse = zeichen(konto.get("avatar"));
        }
        let pfad = budget.bild(adresse).await;
        if !pfad.is_empty() {
            symbol = pfad;
        }
    }

    let (mut bilder_pfade, mut video) = (Vec::new(), false);
    if cfg.bilder() {
        if let Some(Value::Array(anhaenge)) = gezeigt.get("media_attachments") {
            for anhang in anhaenge {
                match zeichen(anhang.get("type")) {
                    "video" | "gifv" => {
                        video = true;
                        continue;
                    }
                    "image" => {}
                    _ => continue,
                }
                // Die Vorschau, nicht das Original: ein Feed-Eintrag zeigt ein
                // Daumennagelbild, die volle Groesse waeren Megabytes ohne
                // sichtbaren Gewinn.
                let mut adresse = zeichen(anhang.get("preview_url"));
                if adresse.is_empty() {
                    adresse = zeichen(anhang.get("url"));
                }
                let pfad = budget.bild(adresse).await;
                if !pfad.is_empty() {
                    bilder_pfade.push(pfad);
                }
            }
        }
    }

    let zeitstempel = {
        let wert = zeichen(status.get("created_at"));
        if wert.is_empty() {
            chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
        } else {
            wert.to_string()
        }
    };

    feed::Eintrag {
        symbol,
        titel: wer,
        text: inhalt,
        fusszeile: fusszeile.to_string(),
        zeitstempel,
        bilder: bilder_pfade,
        video,
        ziel: text::linkziel(&gezeigt, &cfg.instanz()),
    }
}

/// Ein Abruf. Zurueck kommen die beiden neuen Marken; gesichert werden sie
/// vom Aufrufer.
async fn abrufen(
    klient: &mastodon::Klient,
    ansicht: &feed::Ereignisansicht<'_>,
    cfg: &Einstellungen,
) -> Result<(String, String), mastodon::Fehler> {
    let (host, token) = (cfg.instanz(), cfg.token());
    let mut budget = bilder::Budget::neu(
        klient,
        if cfg.bilder() || cfg.avatare() { bilder::JE_ABRUF } else { 0 },
    );
    let mut marke_startseite = cfg.marke_startseite();
    let mut marke_erwaehnungen = cfg.marke_erwaehnungen();

    if cfg.startseite() {
        let beitraege = klient.zeitleiste(&host, &token, &marke_startseite).await?;
        for status in beitraege.iter().rev() {
            let eintrag = eintrag_bauen(status, ANZEIGE, &mut budget, cfg).await;
            if let Err(e) = ansicht.eintragen(&eintrag, QUELLE, ANZEIGE).await {
                // Lieber ein Beitrag weniger als der ganze Durchlauf: haengt
                // der Durchlauf, rueckt die Marke nicht vor und der naechste
                // Abruf stolpert ueber genau denselben Beitrag.
                melden(&format!("Beitrag ausgelassen ({}): {}", kennung(status), kette(e.as_ref())));
            }
        }
        if let Some(erster) = beitraege.first() {
            marke_startseite = kennung(erster);
        }
    }

    if cfg.erwaehnungen() {
        let meldungen = klient.erwaehnungen(&host, &token, &marke_erwaehnungen).await?;
        for meldung in meldungen.iter().rev() {
            let status = match meldung.get("status") {
                Some(s) if !s.is_null() => s,
                _ => continue,
            };
            let art = match zeichen(meldung.get("type")) {
                "mention" => "Erwaehnung",
                "favourite" => "Favorit",
                "reblog" => "Geteilt",
                andere => andere,
            };
            let eintrag = eintrag_bauen(status, art, &mut budget, cfg).await;
            if let Err(e) = ansicht.eintragen(&eintrag, QUELLE, ANZEIGE).await {
                melden(&format!("Beitrag ausgelassen ({}): {}", kennung(status), kette(e.as_ref())));
            }
        }
        if let Some(erste) = meldungen.first() {
            marke_erwaehnungen = kennung(erste);
        }
    }

    bilder::kappen();
    Ok((marke_startseite, marke_erwaehnungen))
}

/// Schlafen, aber jede Minute nachsehen, ob der Schalter umgelegt wurde oder
/// eine neue Fassung installiert ist.
///
/// Das Abfrageintervall sind zehn Minuten. Wer den Feed abschaltet, tut das
/// genau dann, wenn er nichts mehr geladen haben will -- und nicht erst in
/// zehn Minuten.
async fn warten(sekunden: u64, stand: Option<(u64, u64)>) {
    let mut rest = sekunden;
    while rest > 0 {
        let stueck = rest.min(60);
        tokio::time::sleep(std::time::Duration::from_secs(stueck)).await;
        rest -= stueck;
        if !Einstellungen::laden().an() || abgeloest(stand) {
            return;
        }
    }
}

async fn dienst() -> i32 {
    let stand = eigener_stand();
    let bus = match feed::verbinden().await {
        Ok(b) => b,
        Err(e) => {
            // Ohne Sitzungsbus gibt es ohnehin keinen Feed, in den
            // geschrieben werden koennte -- aber sagen statt schweigen.
            melden(&format!("kein Sitzungsbus: {}", kette(e.as_ref())));
            return 1;
        }
    };
    match feed::namen_beanspruchen(&bus).await {
        Ok(true) => {}
        Ok(false) => {
            melden("laeuft bereits, dieser Start endet hier");
            return 0;
        }
        Err(e) => {
            melden(&format!("Bus-Name nicht zu bekommen: {}", e));
            return 1;
        }
    }
    melden(&format!(
        "gestartet {} als uid {}",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S"),
        eigene_uid()
    ));

    let klient = match mastodon::Klient::neu() {
        Ok(k) => k,
        Err(e) => {
            melden(&format!("kein HTTPS-Klient: {}", e));
            return 1;
        }
    };

    // Nur beim Wechsel ins Log: sonst stuenden nach einer Nacht tausend
    // gleiche Zeilen darin, und die eine, auf die es ankommt, faende niemand.
    let mut gesagt = "";
    loop {
        if abgeloest(stand) {
            melden("neue Fassung installiert, dieser Dienst endet");
            return 0;
        }
        let cfg = Einstellungen::laden();
        if !cfg.an() {
            if gesagt != "aus" {
                melden("abgeschaltet, es wird nichts geholt");
                gesagt = "aus";
            }
            tokio::time::sleep(std::time::Duration::from_secs(60)).await;
            continue;
        }
        if !cfg.eingerichtet() {
            // Noch nicht eingerichtet. Schlafen statt enden: die
            // Einstellungsseite kann das jederzeit nachholen.
            if gesagt != "leer" {
                melden("kein Konto eingerichtet, warte");
                gesagt = "leer";
            }
            tokio::time::sleep(std::time::Duration::from_secs(60)).await;
            continue;
        }
        if gesagt == "aus" {
            melden("wieder eingeschaltet");
        }
        gesagt = "an";

        match feed::Ereignisansicht::neu(&bus).await {
            Ok(ansicht) => match abrufen(&klient, &ansicht, &cfg).await {
                Ok((h, e)) => {
                    if let Err(f) = einstellungen::marken_sichern(&h, &e) {
                        melden(&format!("Marken nicht gesichert: {}", f));
                    }
                }
                Err(e) => melden(&format!("mastodon: {}", kette(e.as_ref()))),
            },
            Err(e) => melden(&format!("Ereignisansicht: {}", kette(e.as_ref()))),
        }
        warten(cfg.intervall(), stand).await;
    }
}

/// `--probe <instanz>`: holt den Namen einer Instanz. Beweist auf dem Geraet,
/// dass TLS 1.2 und die Namensaufloesung stehen -- ohne Konto und ohne Token.
async fn probe(host: &str) -> i32 {
    AUCH_AUF_DEM_SCHIRM.store(true, Ordering::Relaxed);
    match mastodon::Klient::neu() {
        Ok(k) => match k.instanz_titel(host).await {
            Ok(titel) => {
                println!("{} heisst \"{}\"", host, titel);
                0
            }
            Err(e) => {
                println!("{}: {}", host, kette(e.as_ref()));
                1
            }
        },
        Err(e) => {
            println!("kein Klient: {}", e);
            1
        }
    }
}

/// `--eintrag <datei.json>`: traegt einen Beitrag aus einer Datei in die
/// Ereignisansicht ein. Prueft den ganzen Weg bis zum Feed -- Sitzungsbus,
/// Dictionary, Link -- ohne Konto.
async fn eintrag_aus_datei(datei: &str) -> i32 {
    AUCH_AUF_DEM_SCHIRM.store(true, Ordering::Relaxed);
    let status: Value = match std::fs::read_to_string(datei)
        .map_err(|e| e.to_string())
        .and_then(|t| serde_json::from_str(&t).map_err(|e| e.to_string()))
    {
        Ok(v) => v,
        Err(e) => {
            println!("{}: {}", datei, e);
            return 1;
        }
    };
    let bus = match feed::verbinden().await {
        Ok(b) => b,
        Err(e) => {
            println!("kein Sitzungsbus: {}", e);
            return 1;
        }
    };
    let ansicht = match feed::Ereignisansicht::neu(&bus).await {
        Ok(a) => a,
        Err(e) => {
            println!("Ereignisansicht: {}", e);
            return 1;
        }
    };
    let klient = match mastodon::Klient::neu() {
        Ok(k) => k,
        Err(e) => {
            println!("kein Klient: {}", e);
            return 1;
        }
    };
    let cfg = Einstellungen::laden();
    let mut budget = bilder::Budget::neu(&klient, 0);
    let eintrag = eintrag_bauen(&status, "Mastodon (Probe)", &mut budget, &cfg).await;
    println!("Ziel: {:?}", eintrag.ziel);
    match ansicht.eintragen(&eintrag, QUELLE, ANZEIGE).await {
        Ok(k) => {
            println!("addItem -> {}", k);
            if k < 0 { 1 } else { 0 }
        }
        Err(e) => {
            println!("addItem: {}", kette(e.as_ref()));
            1
        }
    }
}

/// `--trocken`: holt mit dem eingerichteten Konto die letzten Beitraege und
/// sagt, was daraus wuerde -- ohne etwas in den Feed zu legen und ohne die
/// Marken zu bewegen. Damit laesst sich die Anmeldung auf dem Geraet pruefen,
/// ohne dem Nutzer zwanzig alte Beitraege in die Ereignisansicht zu kippen.
async fn trockenlauf() -> i32 {
    AUCH_AUF_DEM_SCHIRM.store(true, Ordering::Relaxed);
    let cfg = Einstellungen::laden();
    if !cfg.eingerichtet() {
        println!("kein Konto eingerichtet");
        return 1;
    }
    let klient = match mastodon::Klient::neu() {
        Ok(k) => k,
        Err(e) => {
            println!("kein Klient: {}", kette(e.as_ref()));
            return 1;
        }
    };
    println!("Konto auf {}", cfg.instanz());
    match klient.zeitleiste(&cfg.instanz(), &cfg.token(), "").await {
        Ok(beitraege) => {
            println!("Startseite: {} Beitraege", beitraege.len());
            for status in beitraege.iter().take(5) {
                let wer = zeichen(
                    status
                        .get("account")
                        .and_then(|k| k.get("acct")),
                );
                let ziel = text::linkziel(status, &cfg.instanz());
                let zeile: String = text::klartext(zeichen(status.get("content")))
                    .chars()
                    .take(50)
                    .collect();
                println!(
                    "  @{} | {} | {}",
                    wer,
                    zeile.replace('\n', " "),
                    if ziel.is_empty() { "(kein Link)" } else { &ziel }
                );
            }
        }
        Err(e) => {
            println!("Startseite: {}", kette(e.as_ref()));
            return 1;
        }
    }
    match klient.erwaehnungen(&cfg.instanz(), &cfg.token(), "").await {
        Ok(meldungen) => println!("Erwaehnungen: {} Meldungen", meldungen.len()),
        Err(e) => {
            println!("Erwaehnungen: {}", kette(e.as_ref()));
            return 1;
        }
    }
    0
}

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let args: Vec<String> = std::env::args().collect();
    let ende = match args.get(1).map(String::as_str) {
        Some("--probe") => probe(args.get(2).map(String::as_str).unwrap_or("")).await,
        Some("--eintrag") => eintrag_aus_datei(args.get(2).map(String::as_str).unwrap_or("")).await,
        Some("--trocken") => trockenlauf().await,
        Some(anderes) => {
            println!("unbekannt: {} (bekannt: --probe <instanz>, --trocken, --eintrag <datei>)", anderes);
            2
        }
        None => dienst().await,
    };
    std::process::exit(ende);
}
