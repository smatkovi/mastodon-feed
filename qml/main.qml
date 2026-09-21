import QtQuick 1.1
import com.nokia.meego 1.0

// Settings page for the Mastodon feed. QtQuick 1.1, so: no readonly, no
// "property var", and the account object comes from the root context rather
// than from a singleton.
PageStackWindow {
    id: app
    showStatusBar: true
    showToolBar: false

    Component.onCompleted: theme.inverted = true

    initialPage: Page {
        id: page
        orientationLock: PageOrientation.Automatic

        Flickable {
            anchors.fill: parent
            contentHeight: column.height + 32
            // Without this the page will not scroll once a text field has the
            // press -- a QtQuick 1.1 Flickable never steals it back otherwise.
            pressDelay: 150
            clip: true

            Column {
                id: column
                width: page.width
                spacing: 12
                y: 12

                Item { width: 1; height: 8 }

                Label {
                    x: 16
                    width: parent.width - 32
                    text: "Mastodon"
                    font.pixelSize: 32
                    color: "#4c8fd6"
                }

                Label {
                    x: 16
                    width: parent.width - 32
                    wrapMode: Text.WordWrap
                    font.pixelSize: 18
                    color: "#b0b0b0"
                    text: account.connected
                          ? "Angemeldet als @" + account.account + " auf " + account.instance
                          : "Der Browser dieses Geräts ist zu alt für Mastodons "
                            + "Anmeldeseite, deshalb läuft die Anmeldung hier direkt "
                            + "über die Zugangsdaten."
                }

                // ---- sign in ------------------------------------------------
                Column {
                    width: parent.width
                    spacing: 10
                    visible: !account.connected

                    Label { x: 16; text: "Instanz"; font.pixelSize: 18; color: "#b0b0b0" }
                    TextField {
                        id: instanceField
                        x: 16
                        width: parent.width - 32
                        placeholderText: "z. B. graz.social"
                        text: account.instance
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                    }

                    // The token route first: Mastodon 4 turns the password
                    // grant off on most instances, so this is the one that
                    // actually works.
                    Label {
                        x: 16
                        width: parent.width - 32
                        wrapMode: Text.WordWrap
                        font.pixelSize: 16
                        color: "#909090"
                        text: "Zugriffstoken: auf der Instanz unter Einstellungen \u2192 "
                              + "Entwicklung \u2192 Neue Anwendung, Recht \u201eread\u201c, "
                              + "dann \u201eZugangstoken\u201c kopieren."
                    }
                    TextField {
                        id: tokenField
                        x: 16
                        width: parent.width - 32
                        placeholderText: "Zugriffstoken"
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                    }
                    Button {
                        x: 16
                        width: parent.width - 32
                        text: account.busy ? "Bitte warten \u2026" : "Mit Token anmelden"
                        enabled: !account.busy
                        onClicked: account.signInWithToken(instanceField.text, tokenField.text)
                    }

                    Label {
                        x: 16
                        width: parent.width - 32
                        wrapMode: Text.WordWrap
                        font.pixelSize: 16
                        color: "#707070"
                        text: "Oder mit Passwort \u2014 das erlauben aber die "
                              + "wenigsten Instanzen noch, und mit Zwei-Faktor-Anmeldung nie."
                    }

                    Label { x: 16; text: "Benutzername oder E-Mail"; font.pixelSize: 18; color: "#b0b0b0" }
                    TextField {
                        id: userField
                        x: 16
                        width: parent.width - 32
                        inputMethodHints: Qt.ImhNoAutoUppercase | Qt.ImhNoPredictiveText
                    }

                    Label { x: 16; text: "Passwort"; font.pixelSize: 18; color: "#b0b0b0" }
                    TextField {
                        id: passField
                        x: 16
                        width: parent.width - 32
                        echoMode: TextInput.Password
                    }

                    Button {
                        x: 16
                        width: parent.width - 32
                        text: account.busy ? "Bitte warten …" : "Anmelden"
                        enabled: !account.busy
                        onClicked: account.signIn(instanceField.text, userField.text, passField.text)
                    }
                }

                // ---- what goes into the feed --------------------------------
                Column {
                    width: parent.width
                    spacing: 10
                    visible: account.connected

                    Row {
                        x: 16
                        spacing: 12
                        Switch {
                            // Set once and written back only on a real change:
                            // binding checked to the account and assigning to
                            // the account from checked is a loop.
                            Component.onCompleted: checked = account.home
                            onCheckedChanged: if (checked !== account.home) account.setHome(checked)
                        }
                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Startseite im Feed"
                            font.pixelSize: 20
                        }
                    }

                    Row {
                        x: 16
                        spacing: 12
                        Switch {
                            // Set once and written back only on a real change:
                            // binding checked to the account and assigning to
                            // the account from checked is a loop.
                            Component.onCompleted: checked = account.mentions
                            onCheckedChanged: if (checked !== account.mentions) account.setMentions(checked)
                        }
                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Erwähnungen im Feed"
                            font.pixelSize: 20
                        }
                    }

                    Row {
                        x: 16
                        spacing: 12
                        Switch {
                            Component.onCompleted: checked = account.avatars
                            onCheckedChanged: if (checked !== account.avatars) account.setAvatars(checked)
                        }
                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Profilbilder laden"
                            font.pixelSize: 20
                        }
                    }

                    Row {
                        x: 16
                        spacing: 12
                        Switch {
                            Component.onCompleted: checked = account.images
                            onCheckedChanged: if (checked !== account.images) account.setImages(checked)
                        }
                        Label {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Bilder laden"
                            font.pixelSize: 20
                        }
                    }

                    Label {
                        x: 16
                        width: parent.width - 32
                        wrapMode: Text.WordWrap
                        font.pixelSize: 16
                        color: "#909090"
                        text: "Beides aus lässt der Feed rein aus Text bestehen \u2014 "
                              + "auf 2G die schnellste Einstellung. Geladen werden nur "
                              + "Vorschaubilder, nie die Bilder in voller Größe."
                    }

                    Button {
                        x: 16
                        width: parent.width - 32
                        text: "Abmelden"
                        onClicked: account.signOut()
                    }
                }

                // ---- what just happened -------------------------------------
                Label {
                    x: 16
                    width: parent.width - 32
                    wrapMode: Text.WordWrap
                    visible: account.status !== ""
                    text: account.status
                    font.pixelSize: 18
                    color: "#e0c060"
                }

                Item { width: 1; height: 16 }
            }
        }

        BusyIndicator {
            anchors.centerIn: parent
            running: account.busy
            visible: account.busy
        }
    }
}
