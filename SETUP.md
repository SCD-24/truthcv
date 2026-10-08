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
- **Linux** — `truthcv.sh`. If double-clicking opens it in a text editor
  instead of running it, right-click it and choose "Run as a Program"
  (some file managers call this "Execute").

The first start takes about ten minutes, because your computer is
building TruthCV. That happens once. Every start after it takes a few
seconds.

When it is ready your browser opens at <http://localhost:5627>. If your
computer was already using port 5627, the launcher picks the next free
port instead, so the address may differ (for example
`http://localhost:5628`); the launcher prints the one it chose.

## Finishing setup in the browser

TruthCV walks you through the rest:

1. **Connect a model provider** — choose Claude, ChatGPT, OpenRouter or
   Ollama, then pick a default model. Claude and ChatGPT let you sign in
   with your subscription instead of an API key; OpenRouter needs an API
   key; Ollama needs no credential, just its URL.
2. **Upload your CV** — a PDF, DOCX, TXT or Markdown file (a LinkedIn PDF
   export is the easiest). Review what TruthCV extracted; this becomes your
   truth file, the only source of facts TruthCV is allowed to use.

That is all onboarding asks for. Two things are only needed if you want
TruthCV to apply to jobs for you, and are done later in the app:

- **Your details** (name, email, phone and the other questions job
  applications always ask) are filled in on the **Agents** page.
- **Target companies** are part of the agent configuration, not onboarding.

## If something goes wrong

**"Docker Desktop isn't running"** — start Docker Desktop, wait for the
whale icon to settle, then double-click the launcher again.

**Nothing opens** — open the address the launcher printed yourself
(<http://localhost:5627> unless that port was taken and it picked another).
It may still be starting.

**Stopping TruthCV** — quit Docker Desktop. Your data stays where it is.

Your CVs and applications are stored on your computer, in the `data`
folder; job-board sign-ins are kept in the separate Docker volume
`browser-profile`. The text of your CV is sent to the model provider you
choose in order to read and tailor it. With Ollama it goes to whatever
Ollama server you configured — it stays on your computer only if that
server runs locally.
