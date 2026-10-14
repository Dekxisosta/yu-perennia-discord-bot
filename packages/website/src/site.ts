export const INVITE_URL: string = import.meta.env.PUBLIC_INVITE_URL || '#run';
export const REPO_URL: string =
  import.meta.env.PUBLIC_REPO_URL || 'https://github.com/yourusername/yu-perennia-bot';
export const HAS_INVITE = Boolean(import.meta.env.PUBLIC_INVITE_URL);
export const HAS_REPO = Boolean(import.meta.env.PUBLIC_REPO_URL);
