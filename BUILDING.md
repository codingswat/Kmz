# Making the Windows and Mac apps yourself

You need a Windows PC to make the `.exe`, and a Mac to make the `.dmg`.
A program can only be built on the same kind of computer it runs on.

Each one takes about 5 minutes.

---

## On a Mac

**1. Install Python** (skip if you already have it)

Download from https://www.python.org/downloads/ and run the installer.

**2. Get the code**

Open the Terminal app, then paste this and press Enter:

```bash
git clone https://github.com/codingswat/Kmz.git
cd Kmz
```

**3. Build it**

Paste these one at a time:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui,web,dev]" pyinstaller
pyinstaller build.spec --noconfirm
```

**4. Check it works**

```bash
./dist/KmzPoints.app/Contents/MacOS/KmzPoints --selftest
```

You should see a list ending in **PASS**. If you do, the app is good.

**5. Make the .dmg**

```bash
mkdir -p staging
cp -R dist/KmzPoints.app staging/
ln -s /Applications staging/Applications
hdiutil create -volname "KML KMZ Point Extractor" -srcfolder staging -ov -format UDZO KmzPoints.dmg
```

Your file is **KmzPoints.dmg** in that folder.

---

## On a Windows PC

**1. Install Python** (skip if you already have it)

Download from https://www.python.org/downloads/.
**Important:** on the first screen, tick the box that says
*"Add Python to PATH"* before clicking Install.

**2. Get the code**

Open Command Prompt, then paste this and press Enter:

```
git clone https://github.com/codingswat/Kmz.git
cd Kmz
```

(No git? Download the ZIP from the GitHub page instead, unzip it, and open
Command Prompt inside that folder.)

**3. Build it**

Paste these one at a time:

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[gui,web,dev]" pyinstaller
pyinstaller build.spec --noconfirm
```

**4. Check it works**

```
dist\KmzPoints.exe --selftest
```

You should see a list ending in **PASS**.

Your file is **dist\KmzPoints.exe**. That single file is the whole app —
you can copy it anywhere.

---

## Running the service for colleagues

The desktop app and the service are separate things. Colleagues install
nothing; they open a browser.

On your Mac:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[web]"
KMZ_PASSWORD='pick-something' python serve.py
```

It prints the address to share, for example `http://192.168.1.42:8000`. Give
colleagues that link and the password. Stop it with Ctrl-C. Leave off
`KMZ_PASSWORD` and it asks you for one instead of taking it from the command
line, which keeps it out of your shell history.

Three things to know before you hand the link out:

- It only works while your laptop is awake, running that command, and on the
  same network. Colleagues cannot tell "it's down" from "you went home".
- The address changes when your laptop gets a new one from DHCP, so re-read
  what the command prints rather than saving the link.
- Traffic is plain HTTP. The password and the files are readable by anyone who
  can watch that network. It is meant for a trusted office LAN, not the
  internet.

The service is deliberately not part of the `.exe` or `.dmg` — `build.spec`
excludes Flask. Only you run the server.

## The warning message

These apps are not signed with a paid certificate, so:

- **Windows** shows a blue "Windows protected your PC" box.
  Click *More info*, then *Run anyway*.
- **Mac** says the app "cannot be opened because it is from an
  unidentified developer". Right-click the app and choose *Open*, then
  click *Open* in the box that appears. You only do this once.

Removing these warnings needs a paid certificate from Apple (about $99 a
year) and one from a Windows certificate seller. Nothing else removes them.

---

## If something goes wrong

Run this to check the plain Python version works before blaming the build:

```
python -m pytest -q
```

All tests should pass. If they do but the built app misbehaves, the problem
is in the packaging step, not the program.
