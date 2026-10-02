// Wake-up service for the PSN price bot (Cloudflare Worker, free plan).
//
// GitHub's own cron for the bot is unreliable, so this Worker runs every minute
// (Cron Trigger "* * * * *") and starts the GitHub workflow:
//   - right away when someone has sent the bot a Telegram message  -> replies in ~1-2 min
//   - every 5 minutes regardless                                    -> price scans and alerts
// It only peeks at Telegram (getUpdates without an offset confirms nothing);
// the bot itself reads and answers the messages.
//
// Secrets (Worker → Settings → Variables and Secrets):
//   TELEGRAM_BOT_TOKEN  the bot token from @BotFather
//   GH_TOKEN            fine-grained GitHub token: this repo only, Actions = Read and write

const REPO = "guyeinat123/psindiacards";
const WORKFLOW = "bot.yml";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(check(env, new Date(event.scheduledTime)));
  },
  // Opening the Worker's URL shows whether it can see Telegram, without starting anything.
  async fetch(request, env) {
    const pending = await hasMessages(env);
    return Response.json({ ok: true, telegram_messages_waiting: pending });
  },
};

async function check(env, now) {
  const pending = await hasMessages(env);
  const everyFive = now.getUTCMinutes() % 5 === 0;
  if (!pending && !everyFive) return;
  const resp = await fetch(
    `https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "psn-price-bot-wakeup",
      },
      body: JSON.stringify({ ref: "main" }),
    },
  );
  if (resp.status !== 204) {
    console.log("dispatch failed", resp.status, await resp.text());
  }
}

async function hasMessages(env) {
  try {
    const r = await fetch(
      `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/getUpdates?timeout=0&limit=1`,
    );
    const data = await r.json();
    return Boolean(data.ok && data.result && data.result.length);
  } catch (e) {
    return false;
  }
}
