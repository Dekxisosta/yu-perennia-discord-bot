 <div align="center">

# Yu Perennia

**A cheerful, modular Discord bot ready to serve your community.**

[![discord.py](https://img.shields.io/badge/discord.py-2.4.0-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![DeepL](https://img.shields.io/badge/DeepL-Translation-0F2B46?style=flat-square&logo=deepl&logoColor=white)](https://www.deepl.com/)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)
[![Status](https://img.shields.io/badge/Status-In_Development-yellow?style=flat-square)]()

<img src="docs/images/yu.webp" alt="Yu Perennia" width="200" height="200" />

</div>

---

## Features

### General Commands

Fun and interactive commands to engage your community.

| Command | Description |
|---|---|
| `greet` | Receive a warm greeting from Yu. |
| `ping` | Check the bot's latency. |
| `info` | Learn about Yu and her capabilities. |
| `quote` | Get an encouraging message. |
| `say` | Make Yu repeat your message. |
| `roll` | Roll a six-sided die. |
| `8ball` | Ask Yu a question and receive a fortune. |
| `coinflip` | Flip a coin. |
| `choose` | Let Yu choose from multiple options. |

### Moderation

Tools to help keep your server safe and organized.

| Command | Description |
|---|---|
| `kick` | Remove a member from the server with the appropriate permissions. |

### Translation

Powered by the DeepL API, Yu can help bridge language barriers in your community.

- **Automatic translation:** Configure channels to translate between English and Chinese or Japanese.
- **On-demand translation:** Translate individual messages into supported languages.
- **Channel controls:** Enable or disable automatic translation as needed.

*Translation features require a DeepL API key.*

### Developer Features

Designed with modularity and maintainability in mind.

- **Dynamic autoloader:** Automatically discovers and loads commands and events.
- **Centralized logging:** Console and file-based logging for debugging.
- **YAML configuration:** Customize command settings and responses without changing application code.
- **Modular architecture:** Separate commands, events, services, utilities, and UI components.
- **SQLite support:** Planned persistent storage for future features.

---

## Requirements

- Python 3.11 or later
- `discord.py` 2.4.0 or later
- A Discord bot token
- A DeepL API key (optional; required for translation features)

---

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/yu-perennia-bot.git
cd yu-perennia-bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and provide your credentials.

```env
DISCORD_TOKEN=your-discord-bot-token
DEEPL_API_KEY=your-deepl-api-key
```

The DeepL API key is optional if you do not intend to use translation features.

### 4. Run the Bot

```bash
python src/main.py
```

---

## Usage

Yu supports both **slash commands** and **prefix commands** using `yp!`.

### General Commands

| Slash Command | Prefix Command | Description |
|---|---|---|
| `/greet` | `yp!greet` | Greets the user. |
| `/ping` | `yp!ping` | Displays bot latency. |
| `/info` | `yp!info` | Displays bot information. |
| `/quote` | `yp!quote` | Shares an encouraging message. |
| `/say <message>` | `yp!say <message>` | Repeats the provided message. |
| `/roll` | `yp!roll` | Rolls a six-sided die. |
| `/8ball <question>` | `yp!8ball <question>` | Answers with a fortune. |
| `/coinflip` | `yp!coinflip` | Flips a coin. |
| `/choose <options>` | `yp!choose option1\|option2\|option3` | Chooses from the provided options. |

### Moderation Commands

| Slash Command | Prefix Command | Description |
|---|---|---|
| `/kick <user> [reason]` | `yp!mod kick <user> [reason]` | Kicks a member from the server. |

### Translation Commands

| Command | Description |
|---|---|
| `/translate chinese` | Enables automatic English–Chinese translation in the current channel. |
| `/translate japanese Hello!` | Translates the provided text into Japanese. |
| `/translate off` | Disables automatic translation in the current channel. |

Exact command syntax may vary depending on the implemented command handlers and configuration.

---

## Configuration

### Command Prefix

Edit `config/bot_defaults.py` to change the default prefix.

```python
DEFAULT_PREFIX = "yp!"
```

### Command Settings

Customize command behavior and messages through the YAML files in `config/commands/`.

- `general_config.yaml` — General commands and responses.
- `mod_config.yaml` — Moderation settings.
- `utility_config.yaml` — Utility command settings.
- `translate_config.yaml` — Translation settings and messages.

---

## Project Structure

```text
yu-perennia-bot/
├── config/
│   ├── commands/
│   ├── bot_defaults.py
│   ├── directories.py
│   └── system_details.py
├── src/
│   ├── cogs/
│   │   ├── commands/
│   │   └── events/
│   ├── core/
│   ├── datastore/
│   ├── factories/
│   ├── services/
│   ├── ui/
│   ├── utils/
│   └── main.py
├── tests/
├── .env.example
├── .gitignore
├── LICENSE
└── requirements.txt
```

---

## Contributing

Contributions are welcome. You can help improve Yu by:

- Reporting bugs and unexpected behavior.
- Suggesting new features.
- Submitting pull requests.

Please ensure your changes are tested and consistent with the project's existing architecture.

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Acknowledgments

- [discord.py](https://discordpy.readthedocs.io/) — Python wrapper for the Discord API.
- [DeepL](https://www.deepl.com/) — Translation API.
- Character concept and inspiration: Yu Perennia, the goat girl waitress of Cafe Camellia.

<div align="center">

**Made with ☕ by Yu Perennia**

*“Welcome in! Leave it to me!”* 🐐

</div>