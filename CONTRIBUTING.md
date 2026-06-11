# Contributing

Beiträge sind willkommen — danke, dass du mithelfen willst! Bitte ein paar Dinge vorab.

## Lizenz deiner Beiträge (CLA)

`yoka-cubase-mcp` wird **dual-lizenziert** (AGPL-3.0 + kommerzielle Lizenz, siehe
[`LICENSING.md`](LICENSING.md)). Damit der Projekt-Inhaber Beiträge in **beide**
Lizenz-Arme aufnehmen kann, gilt für jeden Beitrag:

> Mit dem Einreichen eines Pull Requests stimmst du zu, dass dein Beitrag unter
> **AGPL-3.0** veröffentlicht wird **und** dass du dem Projekt-Inhaber (Yoka) ein
> unwiderrufliches, weltweites, gebührenfreies Recht einräumst, deinen Beitrag auch
> unter einer **kommerziellen Lizenz** zu verwerten.

Ohne diese Zustimmung kann ein Beitrag nicht gemerged werden. Dies ist ein einfaches
*Inbound = AGPL + kommerzielle Verwertung*-CLA; bei größeren Beiträgen ggf. ein
separat signiertes CLA.

## Workflow

- **Issue zuerst** für Bugs/Ideen — kurz abstimmen, bevor du viel Arbeit investierst.
- Branch von `main`, fokussierte Commits, PR mit Beschreibung.
- Offline-Selftests laufen lassen: `python -m tests.selftests.listener_selftest` u. a.
- Keine Secrets/persönlichen Pfade in Commits (Repo ist public).

---

*Kein Rechtsrat — der CLA-Wortlaut ist eine Vorlage; vor produktivem Geldfluss
juristisch prüfen lassen.*
