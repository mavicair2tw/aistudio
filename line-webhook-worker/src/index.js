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

async function replyToEvent(event, accessToken) {
  if (event?.type !== 'follow' || !event?.replyToken) return;
  const message = {
    replyToken: event.replyToken,
    messages: [
      {
        type: 'text',
        text: '收到！LINE 推播已啟用，收盤後會自動通知你。'
      }
    ]
  };
  const res = await fetch('https://api.line.me/v2/bot/message/reply', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      authorization: `Bearer ${accessToken}`
    },
    body: JSON.stringify(message)
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

const SUBSCRIBER_KEY = 'line-subscribers';

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

    const { method } = request;
    if (method !== 'POST') {
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
      await Promise.all((body.events || []).map(async evt => {
        if (evt?.source?.userId) {
          await addSubscriber(env, evt.source.userId);
        }
        await replyToEvent(evt, accessToken);
      }));
    } catch (err) {
      console.error('LINE reply failed', err);
    }

    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' }
    });
  }
};
