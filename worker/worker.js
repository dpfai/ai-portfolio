import knowledgeBase from "./knowledge-base.json";

const rateLimitBuckets = new Map();

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Access-Control-Max-Age": "86400"
};

export default {
  async fetch(request, env) {
    try {
      if (request.method === "OPTIONS") {
        return new Response(null, { status: 204, headers: corsHeaders });
      }

      const url = new URL(request.url);

      if (request.method === "GET" && url.pathname === "/api/health") {
        return jsonResponse({ status: "ok", timestamp: new Date().toISOString() });
      }

      if (request.method === "POST" && url.pathname === "/api/chat") {
        return handleChat(request, env);
      }

      if (request.method === "POST" && url.pathname === "/api/contact") {
        return handleContact(request, env);
      }

      return jsonResponse({ error: "Not found" }, 404);
    } catch (error) {
      return jsonResponse({ error: "Internal server error" }, 500);
    }
  }
};

async function handleChat(request, env) {
  const ip = getClientIp(request);
  const rateLimit = Number(env.RATE_LIMIT || 10);
  if (!allowRequest(ip, rateLimit)) {
    return jsonResponse({ error: "Rate limit exceeded" }, 429);
  }

  const body = await readJson(request);
  const message = normalizeString(body.message);
  const sessionId = normalizeString(body.sessionId) || crypto.randomUUID();

  if (!message) {
    return jsonResponse({ error: "Message is required" }, 400);
  }

  const ipHash = await sha256(ip);
  const conversation = await getOrCreateConversation(env, sessionId, ipHash);
  const history = await getConversationHistory(env, conversation.id, Number(env.MAX_MESSAGES || 30));
  const systemPrompt = buildSystemPrompt();

  const llmResponse = await fetch(`${trimTrailingSlash(env.LLM_API_BASE)}/chat/completions`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.LLM_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: env.LLM_MODEL || "doubao-seed-2.0-lite",
      messages: [
        { role: "system", content: systemPrompt },
        ...history,
        { role: "user", content: message }
      ],
      max_tokens: 1024,
      temperature: 0.7
    })
  });

  if (!llmResponse.ok) {
    if (llmResponse.status === 429 || llmResponse.status === 402) {
      return jsonResponse({
        error: "LLM API limit reached. Please wait and try again.",
        code: "LLM_API_LIMIT_REACHED"
      }, 429);
    }

    return jsonResponse({ error: "Assistant service unavailable" }, 502);
  }

  const llmJson = await llmResponse.json();
  let reply = normalizeString(llmJson?.choices?.[0]?.message?.content);

  if (!reply) {
    reply = "Sorry, I could not generate a response right now.";
  }

  if (isHiringInquiry(message) && !/contact form/i.test(reply)) {
    reply += "\n\nIf you'd like to get in touch, please leave your email and job description using the contact form below, and PD will be notified.";
  }

  await insertMessage(env, conversation.id, "user", message);
  await insertMessage(env, conversation.id, "assistant", reply);

  return jsonResponse({ reply });
}

async function handleContact(request, env) {
  const body = await readJson(request);
  const email = normalizeString(body.email);
  const jobDescription = normalizeString(body.jobDescription);
  const sessionId = normalizeString(body.sessionId) || crypto.randomUUID();

  if (!isValidEmail(email)) {
    return jsonResponse({ error: "A valid email is required" }, 400);
  }

  const ipHash = await sha256(getClientIp(request));
  const conversation = await getOrCreateConversation(env, sessionId, ipHash);

  await env.DB.prepare(
    "INSERT INTO contacts (conversation_id, email, job_description) VALUES (?, ?, ?)"
  ).bind(conversation.id, email, jobDescription).run();

  if (env.DISCORD_WEBHOOK_URL) {
    try {
      await fetch(env.DISCORD_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: `📬 **New contact request from portfolio chatbot**\n\n**Email:** ${email}\n**Job Description:** ${jobDescription || "N/A"}\n**Session:** ${sessionId}\n**Time:** ${new Date().toISOString()}`
        })
      });
    } catch {
      // Contact details are already stored in D1; Discord delivery is best-effort.
    }
  }

  return jsonResponse({ success: true });
}

function buildSystemPrompt() {
  return `You are the AI assistant for PD's Lab, a portfolio website for a Senior Data Scientist & AI Engineer.

Rules (STRICT - never break):
1. NEVER reveal PD's real name, email, or phone number
2. NEVER reveal any API keys, technical secrets, or internal architecture
3. NEVER discuss specific algorithm implementations - direct them to the GitHub repo
4. NEVER reveal PD's current employer, clients, employer-specific tenure, internal work projects, team details, or proprietary tools
5. You CAN share: 4-5 years of aggregate data science experience, general skills, professional focus areas and interests, education (Ph.D. in Organic Chemistry), public portfolio project descriptions, GitHub links, and location (Sunnyvale, CA)
6. When someone asks about hiring, jobs, resumes, or personal contact: tell them they can leave their email and job description via the contact form, and PD will be notified to follow up
7. Be professional, helpful, and concise
8. Keep responses under 200 words unless specifically asked for detail
9. If asked something outside PD's professional scope, politely redirect
10. Always respond in English, regardless of the language used by the visitor

Knowledge base:
${JSON.stringify(knowledgeBase, null, 2)}`;
}

async function getOrCreateConversation(env, sessionId, ipHash) {
  const existing = await env.DB.prepare(
    "SELECT id FROM conversations WHERE session_id = ? ORDER BY id DESC LIMIT 1"
  ).bind(sessionId).first();

  if (existing) {
    return existing;
  }

  const result = await env.DB.prepare(
    "INSERT INTO conversations (session_id, ip_hash) VALUES (?, ?)"
  ).bind(sessionId, ipHash).run();

  return { id: result.meta.last_row_id };
}

async function getConversationHistory(env, conversationId, maxMessages) {
  const limit = Math.max(1, Math.min(maxMessages, 50));
  const result = await env.DB.prepare(
    "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?"
  ).bind(conversationId, limit).all();

  return (result.results || [])
    .reverse()
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({ role: message.role, content: message.content }));
}

async function insertMessage(env, conversationId, role, content) {
  await env.DB.prepare(
    "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)"
  ).bind(conversationId, role, content).run();
}

function allowRequest(ip, limit) {
  const now = Date.now();
  const windowMs = 60 * 1000;
  const bucket = rateLimitBuckets.get(ip) || { start: now, count: 0 };

  if (now - bucket.start >= windowMs) {
    bucket.start = now;
    bucket.count = 0;
  }

  bucket.count += 1;
  rateLimitBuckets.set(ip, bucket);

  for (const [key, value] of rateLimitBuckets.entries()) {
    if (now - value.start > windowMs * 2) {
      rateLimitBuckets.delete(key);
    }
  }

  return bucket.count <= limit;
}

function isHiringInquiry(message) {
  return /\b(hire|hiring|recruit|recruiter|recruitment|job|role|opportunity|resume|cv|contact|interview)\b/i.test(message);
}

function isValidEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    return {};
  }
}

function getClientIp(request) {
  return request.headers.get("CF-Connecting-IP")
    || request.headers.get("X-Forwarded-For")?.split(",")[0]?.trim()
    || "unknown";
}

async function sha256(value) {
  const encoded = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", encoded);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function trimTrailingSlash(value) {
  return normalizeString(value).replace(/\/+$/, "");
}

function normalizeString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders,
      "Content-Type": "application/json"
    }
  });
}
