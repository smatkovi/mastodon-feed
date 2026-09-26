//! Aus Mastodons HTML wird eine Zeile Text -- und der Link, auf den ein
//! Beitrag zeigt.

use serde_json::Value;

const ZEICHEN: &[(&str, &str)] = &[
    ("&amp;", "&"),
    ("&lt;", "<"),
    ("&gt;", ">"),
    ("&quot;", "\""),
    ("&#39;", "'"),
    ("&apos;", "'"),
    ("&nbsp;", " "),
];

pub fn entschaerft(text: &str) -> String {
    let mut s = text.to_string();
    for (name, zeichen) in ZEICHEN {
        s = s.replace(name, zeichen);
    }
    s
}

/// Mastodon schickt HTML, der Feed will eine Zeile Text.
pub fn klartext(html: &str) -> String {
    let mut s = html
        .replace("</p><p>", "\n\n")
        .replace("<br />", "\n")
        .replace("<br/>", "\n")
        .replace("<br>", "\n");
    // Keine Regex-Kiste dafuer: ein Zeichen zu merken genuegt, und das
    // Binary bleibt klein.
    let mut ohne = String::with_capacity(s.len());
    let mut in_tag = false;
    for c in s.chars() {
        match c {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => ohne.push(c),
            _ => {}
        }
    }
    s = entschaerft(&ohne);
    s.trim().to_string()
}

/// Der Wert eines Attributs innerhalb eines oeffnenden Tags.
fn attribut(tag: &str, name: &str) -> Option<String> {
    let muster = format!("{}=\"", name);
    let start = tag.find(&muster)? + muster.len();
    let rest = &tag[start..];
    let ende = rest.find('"')?;
    Some(rest[..ende].to_string())
}

/// Der Link, auf den ein Beitrag zeigt -- oder "" fuer keinen.
///
/// Das Feld `action` eines Feed-Eintrags ist fuer die Ereignisansicht eine
/// Adresse: beim Tippen gibt `meegotouchhome` sie an
/// `ContentAction::Action::defaultActionForScheme`, und der Browser hat sich
/// in `browser.desktop` fuer `x-maemo-urischeme/http` und `…/https`
/// eingetragen. Leer heisst: der Eintrag reagiert nicht aufs Tippen.
///
/// Zuerst die Vorschaukarte -- das ist Mastodons eigene Auskunft "dieser
/// Beitrag zeigt auf etwas". Sonst der erste Link im Text, aber ohne
/// Erwaehnungen und Schlagwoerter: die traegt Mastodon als `<a>` mit der
/// Klasse "mention" bzw. "hashtag" ein, und sie fuehren nur auf ein Profil
/// oder eine Schlagwortseite, die dieser Browser ohnehin nicht darstellt.
pub fn linkziel(status: &Value, host: &str) -> String {
    if let Some(karte) = status
        .get("card")
        .and_then(|k| k.get("url"))
        .and_then(Value::as_str)
    {
        if !karte.is_empty() {
            return entschaerft(karte);
        }
    }
    let inhalt = status.get("content").and_then(Value::as_str).unwrap_or("");
    let eigenes_profil = format!("//{}/@", host);
    let mut rest = inhalt;
    while let Some(start) = rest.find("<a ") {
        let nach = &rest[start..];
        let ende = match nach.find('>') {
            Some(e) => e,
            None => break,
        };
        let tag = &nach[..ende];
        rest = &nach[ende..];
        let klassen = attribut(tag, "class").unwrap_or_default();
        if klassen.contains("mention") || klassen.contains("hashtag") {
            continue;
        }
        let adresse = match attribut(tag, "href") {
            Some(a) => entschaerft(&a),
            None => continue,
        };
        // Guertel und Hosentraeger, falls die Klasse einmal fehlt: auf der
        // eigenen Instanz sind /@jemand und /tags/… genau diese beiden Faelle.
        if (!host.is_empty() && adresse.contains(&eigenes_profil)) || adresse.contains("/tags/") {
            continue;
        }
        return adresse;
    }
    String::new()
}

#[cfg(test)]
mod proben {
    use super::*;

    fn beitrag(html: &str) -> Value {
        serde_json::json!({ "content": html })
    }

    #[test]
    fn link_mit_kaufmanns_und() {
        let b = beitrag(r#"<p>News<br><a href="https://fr.de/x?a=1&amp;b=2" rel="nofollow">fr.de</a></p>"#);
        assert_eq!(linkziel(&b, "graz.social"), "https://fr.de/x?a=1&b=2");
    }

    #[test]
    fn erwaehnung_und_schlagwort_zaehlen_nicht() {
        let b = beitrag(r#"<p><a href="https://graz.social/@wer" class="u-url mention">@wer</a> <a href="https://graz.social/tags/x" class="mention hashtag">#x</a></p>"#);
        assert_eq!(linkziel(&b, "graz.social"), "");
    }

    #[test]
    fn karte_schlaegt_text() {
        let b = serde_json::json!({
            "card": {"url": "https://karte.example/"},
            "content": "<a href=\"https://text.example/\">x</a>"
        });
        assert_eq!(linkziel(&b, ""), "https://karte.example/");
    }

    #[test]
    fn text_ohne_tags() {
        assert_eq!(
            klartext("<p>eins</p><p>zwei &amp; drei<br />vier</p>"),
            "eins\n\nzwei & drei\nvier"
        );
    }
}
