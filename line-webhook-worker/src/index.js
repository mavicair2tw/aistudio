const SUBSCRIBER_KEY = 'line-subscribers';
const COMMAND_QUEUE_KEY = 'line-command-queue';
const COMMAND_PREFIX = '#oc';

async function getAccessToken(env) {
  const params = new URLSearchParams({
    grant_type: 'client_credentials',
    client_id: env.LINE_CHANNEL_ID,
    client_secret: env.LINE_CHANNEL_SECRET
  });
  const res = await fetch('https://api.line.me/v2/oauth/accessToken', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: params
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`LINE token error ${res.status}: ${detail}`);
  }
  const data = await res.json();
  return data.access_token;
}

async function replyText(event, accessToken, text) {
  if (!event?.replyToken) return;
  const payload = {
    replyToken: event.replyToken,
    messages: [
      {
        type: 'text',
        text
      }
    ]
  };
  const res = await fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${accessToken}`
    },
    body: JSON.stringify(payload)
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`LINE reply error ${res.status}: ${detail}`);
  }
}

function badRequest(msg) {
  return new Response(msg, { status: 400, headers: { 'content-type': 'text/plain' } });
}

async function handleChartUpload(request) {
  if (request.method !== 'POST') return badRequest('POST only');
  const bytes = await request.arrayBuffer();
  if (!bytes.byteLength) return badRequest('empty body');
  const id = crypto.randomUUID();
  const origin = new URL(request.url).origin;
  const storeUrl = `${origin}/chart-store/${id}`;
  const cacheReq = new Request(storeUrl, { method: 'GET' });
  const response = new Response(bytes, {
    status: 200,
    headers: {
      'content-type': 'image/png',
      'cache-control': 'no-store'
    }
  });
  await caches.default.put(cacheReq, response);
  return new Response(JSON.stringify({ url: storeUrl }), {
    headers: { 'content-type': 'application/json' }
  });
}

async function handleChartStore(request) {
  const cacheKey = new Request(request.url, { method: 'GET' });
  const cached = await caches.default.match(cacheKey);
  if (!cached) return new Response('not found', { status: 404 });
  if (request.method === 'HEAD') {
    return new Response(null, {
      status: cached.status,
      headers: cached.headers
    });
  }
  return cached;
}

async function loadSubscribers(env) {
  const raw = await env.SUBSCRIBERS.get(SUBSCRIBER_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error('Failed to parse subscriber list', err);
    return [];
  }
}

async function saveSubscribers(env, ids) {
  await env.SUBSCRIBERS.put(SUBSCRIBER_KEY, JSON.stringify(ids));
}

async function addSubscriber(env, userId) {
  if (!userId) return;
  const ids = await loadSubscribers(env);
  if (!ids.includes(userId)) {
    ids.push(userId);
    await saveSubscribers(env, ids);
  }
}

async function loadCommandQueue(env) {
  const raw = await env.LINE_COMMANDS.get(COMMAND_QUEUE_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (err) {
    console.error('Failed to parse command queue', err);
    return [];
  }
}

async function saveCommandQueue(env, queue) {
  await env.LINE_COMMANDS.put(COMMAND_QUEUE_KEY, JSON.stringify(queue));
}

async function enqueueCommand(env, command) {
  const queue = await loadCommandQueue(env);
  queue.push(command);
  await saveCommandQueue(env, queue.slice(-200));
}

async function removeCommands(env, ids) {
  if (!ids?.length) return;
  const queue = await loadCommandQueue(env);
  const filtered = queue.filter(cmd => !ids.includes(cmd.id));
  await saveCommandQueue(env, filtered);
}

function normalizeCommand(text) {
  if (!text) return null;
  const trimmed = text.trim();
  if (!trimmed.toLowerCase().startsWith(COMMAND_PREFIX)) return null;
  const payload = trimmed.slice(COMMAND_PREFIX.length).trim();
  if (!payload) return null;
  return payload.replace(/\s+/g, ' ').toUpperCase();
}

function unauthorized() {
  return new Response('unauthorized', { status: 401, headers: { 'content-type': 'text/plain' } });
}

function isAuthorized(request, env) {
  const header = request.headers.get('authorization');
  if (!header) return false;
  const [scheme, token] = header.split(' ');
  if (scheme !== 'Bearer') return false;
  return token === env.COMMAND_API_TOKEN;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/chart-store/')) {
      return handleChartStore(request);
    }
    if (url.pathname === '/chart-upload') {
      return handleChartUpload(request);
    }
    if (url.pathname === '/subscribers') {
      if (request.method === 'GET') {
        const ids = await loadSubscribers(env);
        return new Response(JSON.stringify({ ids }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        });
      }
      if (request.method === 'DELETE') {
        await saveSubscribers(env, []);
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { 'content-type': 'application/json' }
        });
      }
      return new Response('method not allowed', { status: 405 });
    }
    if (url.pathname === '/commands') {
      if (!isAuthorized(request, env)) return unauthorized();
      const commands = await loadCommandQueue(env);
      return new Response(JSON.stringify({ commands }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      });
    }
    if (url.pathname === '/commands/ack') {
      if (!isAuthorized(request, env)) return unauthorized();
      if (request.method !== 'POST') return badRequest('POST only');
      let payload = null;
      try {
        payload = await request.json();
      } catch (err) {
        return badRequest('invalid json');
      }
      const ids = Array.isArray(payload?.ids) ? payload.ids : [];
      await removeCommands(env, ids);
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      });
    }

    if (request.method !== 'POST') {
      return new Response('LINE webhook ready', { status: 200 });
    }

    let body = null;
    try {
      body = await request.json();
    } catch (err) {
      console.error('Failed to parse JSON body', err);
      return new Response(JSON.stringify({ ok: false, error: 'invalid_json' }), {
        status: 400,
        headers: { 'content-type': 'application/json' }
      });
    }

    console.log('LINE webhook payload', JSON.stringify(body));

    try {
      const accessToken = await getAccessToken(env);
      for (const evt of body.events || []) {
        if (evt?.source?.userId) {
          await addSubscriber(env, evt.source.userId);
        }
        if (evt?.type === 'follow') {
          await replyText(evt, accessToken, '收到！LINE 推播已啟用，收盤後會自動通知你。');
          continue;
        }
        if (evt?.type === 'message' && evt.message?.type === 'text') {
          const normalized = normalizeCommand(evt.message.text);
          if (normalized) {
            await enqueueCommand(env, {
              id: crypto.randomUUID(),
              userId: evt.source?.userId || '',
              command: normalized,
              rawText: evt.message.text,
              createdAt: new Date().toISOString()
            });
            await replyText(evt, accessToken, `指令已排程：${normalized}`);
          }
        }
      }
    } catch (err) {
      console.error('LINE reply failed', err);
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  }
};
