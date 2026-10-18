# Yu Perennia website

Neobrutalist landing page for the bot, built with [Astro](https://astro.build) (static output, no client framework).

```bash
cd packages/website
npm install
npm run dev       # http://localhost:4321
npm run build     # outputs to dist/
npm run preview
```

## Configure

Copy `.env.example` to `.env`:

| Variable | Purpose |
| --- | --- |
| `PUBLIC_INVITE_URL` | Target for the "Add to Discord" buttons. Falls back to the self-host section when empty. |
| `PUBLIC_REPO_URL` | Your repository. Used in the clone command and the footer link. |
| `PUBLIC_SUPABASE_URL` / `PUBLIC_SUPABASE_ANON_KEY` | Supabase project for the `/admin` dashboard (see the root README). |

## Structure

- `src/styles/global.css`: palette tokens, type, buttons
- `src/components/`: Header, Hero, OrderPad (interactive demo), Commands, Translate, SelfHost, Footer
- `src/data/lines.ts`: Yu's voice lines, copied from `src/config/commands/general_config.yaml` in the bot
- `public/yu.png`: mascot, also used as favicon

## Palette

`#3a3436` ink, `#e5dadd` paper, `#b9a594` tan, `#aba9b3` mist, `#695752` cocoa, `#a28d86` rose, `#827d81` slate, `#75675f` taupe.
Text sits on ink, paper, tan, mist and cocoa. Rose, slate and taupe are used for large type, fills and shadows only, where they fall below 4.5:1.
