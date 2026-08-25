# Setting up TruthCV

Three steps. You will not need to type any commands.

## 1. Install Docker Desktop

TruthCV runs inside Docker, so install that first:
<https://docs.docker.com/get-docker/>

Download the version for your computer, run the installer, then start
Docker Desktop and wait for its whale icon to stop animating.

## 2. Unzip TruthCV

Unzip the file you were sent, somewhere you will find it again — your
Documents folder is fine. Keep the whole folder together; TruthCV needs
the files next to each other.

## 3. Start it

Open the `scripts/launch` folder inside it and double-click:

- **macOS** — `truthcv.command`
- **Windows** — `truthcv.bat`
- **Linux** — `truthcv.desktop` — first open it in a text editor and
  replace `/path/to/truthcv` on the `Exec=` and `Path=` lines with the
  full path to the folder you unzipped (for example
  `/home/yourname/Documents/truthcv`), then save it and double-click it.
  This one-time edit is needed because a `.desktop` file cannot find its
  own location on its own.

The first start takes about ten minutes, because your computer is
building TruthCV. That happens once. Every start after it takes a few
seconds.

When it is ready your browser opens at <http://localhost:5627>. If your
computer was already using that address TruthCV picks another one and
tells you which.

## Finishing setup in the browser

TruthCV walks you through the rest:

1. **Connect Claude** — sign in with your Claude account. You do not need
   an API key.
2. **Upload your LinkedIn PDF** — this becomes your truth file, the only
   source of facts TruthCV is allowed to use.
3. **Fill in your details** — name, email, phone and the other questions
   job applications always ask.
4. **Choose target companies** — only needed if you want TruthCV to apply
   for you.

## If something goes wrong

**"Docker Desktop isn't running"** — start Docker Desktop, wait for the
whale icon to settle, then double-click the launcher again.

**Nothing opens** — open <http://localhost:5627> yourself. It may still
be starting.

**Stopping TruthCV** — quit Docker Desktop. Your data stays where it is.

Your CVs, applications and sign-ins never leave your computer.
