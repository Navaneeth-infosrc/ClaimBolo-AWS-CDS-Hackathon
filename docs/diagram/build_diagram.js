// Generates docs/architecture.svg. Run: node docs/diagram/build_diagram.js
// Render to PNG with any Chromium browser, e.g.:
//   msedge --headless --force-device-scale-factor=2 --window-size=1690,945 --screenshot=docs/architecture.png docs/architecture.svg
const fs = require("fs");
const path = require("path");

const W = 1690, H = 945;
const C = {
  cds:     { stroke: "#0f766e", fill: "#ecfdf5", text: "#0f3d38" },
  compute: { stroke: "#c2410c", fill: "#fff7ed", text: "#4a1d06" },
  ai:      { stroke: "#6d28d9", fill: "#f5f3ff", text: "#2e1065" },
  data:    { stroke: "#1d4ed8", fill: "#eff6ff", text: "#172554" },
  events:  { stroke: "#be185d", fill: "#fdf2f8", text: "#500724" },
  people:  { stroke: "#334155", fill: "#f8fafc", text: "#0f172a" },
  neutral: { stroke: "#64748b", fill: "#ffffff", text: "#1e293b" },
};
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const out = [];

function zone(x, y, w, h, label, anchor = "start") {
  out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="#f8fafc" stroke="#cbd5e1" stroke-dasharray="6 5"/>`);
  const tx = anchor === "end" ? x + w - 14 : x + 14;
  out.push(`<text x="${tx}" y="${y + 21}" text-anchor="${anchor}" class="zone">${esc(label)}</text>`);
}

function box(x, y, w, h, kind, title, lines = [], opts = {}) {
  const c = C[kind];
  out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="9" fill="${c.fill}" stroke="${c.stroke}" stroke-width="${opts.bold ? 2.4 : 1.6}"${opts.dash ? ' stroke-dasharray="5 4"' : ""}/>`);
  out.push(`<rect x="${x}" y="${y}" width="6" height="${h}" rx="3" fill="${c.stroke}"/>`);
  out.push(`<text x="${x + 16}" y="${y + 22}" class="title" fill="${c.text}">${esc(title)}</text>`);
  lines.forEach((l, i) =>
    out.push(`<text x="${x + 16}" y="${y + 40 + i * 16}" class="${opts.mono ? "mono" : "sub"}">${esc(l)}</text>`));
}

function arrow(d, opts = {}) {
  const color = opts.color || "#475569";
  out.push(`<path d="${d}" fill="none" stroke="${color}" stroke-width="1.8"${opts.dash ? ' stroke-dasharray="5 4"' : ""} marker-end="url(#arrow)"${opts.both ? ' marker-start="url(#arrowStart)"' : ""}/>`);
}

function label(x, y, text, anchor = "middle") {
  out.push(`<text x="${x}" y="${y}" text-anchor="${anchor}" class="label">${esc(text)}</text>`);
}

function step(x, y, n) {
  out.push(`<circle cx="${x}" cy="${y}" r="10" fill="#0f172a"/>`);
  out.push(`<text x="${x}" y="${y + 4}" text-anchor="middle" class="step">${n}</text>`);
}

// ---------- title ----------
out.push(`<text x="30" y="40" class="h1">ClaimBolo · architecture</text>`);
out.push(`<text x="30" y="62" class="h2">WhatsApp voice-first motor claims agent · AWS End User Messaging Social + Amazon SES · us-east-1</text>`);

// ---------- zones ----------
zone(30, 92, 300, 548, "CUSTOMER CHANNELS · AWS CDS");
zone(360, 92, 340, 548, "INGESTION");
zone(740, 92, 520, 548, "AGENT ON AMAZON BEDROCK AGENTCORE", "end");
zone(1290, 92, 370, 308, "DATA AND RULES");
zone(30, 660, 1630, 180, "HUMAN IN THE LOOP AND PROACTIVE UPDATES");

// ---------- customer channels ----------
box(55, 125, 180, 85, "people", "Customer", ["WhatsApp voice notes,", "text and photos", "6 Indian languages"]);
box(55, 260, 250, 110, "cds", "AWS End User Messaging", ["Social (WhatsApp Business)", "SendWhatsAppMessage", "GetWhatsAppMessageMedia"]);
box(55, 495, 250, 95, "cds", "Amazon SES", ["SendEmail (sesv2)", "claim summary to the customer", "alert to the adjuster"]);
arrow("M120,210 V258");
arrow("M180,260 V212");
label(188, 240, "reply", "start");
step(100, 235, 1);

// ---------- ingestion ----------
box(380, 125, 300, 55, "events", "Amazon SNS", ["WhatsApp event topic"]);
box(380, 205, 300, 70, "compute", "Lambda · inbound", ["de-duplicate by message id", "store the message, fetch media"]);
box(380, 300, 300, 55, "data", "Amazon S3 · media", ["KMS-encrypted, private, 30-day expiry"]);
box(380, 380, 300, 65, "ai", "Amazon Transcribe", ["automatic language detection", "ta · hi · en · te · ml · kn"]);
box(380, 470, 300, 50, "events", "Amazon EventBridge", ["transcription finished"]);
box(380, 545, 300, 60, "compute", "Lambda · transcribe-complete", ["adds the transcript to the conversation"]);
arrow("M305,300 H345 V152 H378");
step(345, 226, 2);
arrow("M530,180 V203");
arrow("M530,275 V298"); label(540, 292, "photos, voice notes", "start");
arrow("M530,355 V378"); label(540, 372, "voice notes", "start");
step(505, 367, 3);
arrow("M530,445 V468");
arrow("M530,520 V543");
arrow("M680,240 H712 V150 H763");
arrow("M680,575 H726 V178 H763");

// ---------- agent ----------
box(765, 125, 215, 85, "compute", "Lambda · agent", ["conversation history,", "debounce, reply buttons"]);
box(1020, 125, 215, 85, "ai", "AgentCore Memory", ["customer preferences", "session summaries"]);
arrow("M982,167 H1018", { both: true });
label(1000, 160, "");
// runtime container
out.push(`<rect x="765" y="240" width="470" height="290" rx="10" fill="#faf5ff" stroke="${C.ai.stroke}" stroke-width="2.4"/>`);
out.push(`<text x="781" y="263" class="title" fill="${C.ai.text}">Amazon Bedrock AgentCore Runtime</text>`);
out.push(`<text x="781" y="281" class="sub">src/main.py · Guardrails + tool-use loop + claim tools</text>`);
box(785, 295, 210, 60, "ai", "Bedrock Guardrails", ["input and output checks"]);
box(1010, 295, 205, 60, "ai", "Amazon Bedrock", ["tool use and photo vision"]);
box(785, 370, 430, 145, "neutral", "Claim tools (bound to the sender's number)", [
  "lookup_policy · save_claim_facts · find_missing_items",
  "assess_photo (vision on S3 media) · check_coverage",
  "create_claim · get_claim_status · escalate_to_adjuster",
  "set_language",
  "every tool call is written to the audit table",
], { mono: false });
arrow("M995,325 H1008", {});
arrow("M870,210 V238"); label(880, 229, "InvokeAgentRuntime", "start");
step(850, 225, 4);
box(765, 550, 470, 55, "neutral", "Fallback", ["if the runtime call fails, the agent Lambda runs the same agent code"], { dash: true });

// reply to WhatsApp and email out
arrow("M830,125 V80 H290 V258", { color: C.cds.stroke });
label(560, 75, "SendWhatsAppMessage · replies, buttons, templates");
step(420, 80, 6);
arrow("M785,500 H752 V628 H180 V592", { color: C.cds.stroke });
label(470, 622, "SendEmail · claim registered");
step(330, 628, 6);

// ---------- data and rules ----------
box(1310, 125, 330, 135, "data", "Amazon DynamoDB (KMS)", [
  "policies (mock policy system)",
  "claims (+ phone index)",
  "conversations",
  "audit (every tool call and status change)",
  "processed-messages (de-duplication, TTL)",
]);
box(1310, 285, 330, 95, "compute", "Coverage rules engine", [
  "deterministic: in force, cover type,",
  "deductible, escalation triggers",
  "the model only explains the result",
]);
arrow("M1215,400 H1265 V192 H1308");
arrow("M1215,470 H1278 V332 H1308");
step(1265, 296, 5);

// flow legend
out.push(`<rect x="1290" y="420" width="370" height="220" rx="12" fill="#ffffff" stroke="#cbd5e1"/>`);
out.push(`<text x="1306" y="447" class="zone">FLOW</text>`);
[
  "Customer sends a voice note, text or photo",
  "WhatsApp event reaches SNS and the inbound Lambda",
  "Media is stored in S3; voice is transcribed",
  "Agent Lambda calls AgentCore Runtime",
  "Tools read data, apply rules, check photos",
  "Reply on WhatsApp; claim email through SES",
  "Adjuster acts; customer gets a proactive update",
].forEach((t, i) => {
  step(1316, 474 + i * 23, i + 1);
  out.push(`<text x="1334" y="${478 + i * 23}" class="sub">${esc(t)}</text>`);
});

// ---------- human in the loop ----------
box(55, 695, 290, 120, "people", "Adjuster page", [
  "Lambda function URL, key in Secrets Manager",
  "case file: facts, photos, coverage,",
  "conversation and audit trail",
  "humans decide; the agent prepares",
]);
box(420, 725, 260, 60, "events", "Amazon EventBridge", ["ClaimStatusChanged (survey scheduled)"]);
box(765, 695, 470, 120, "compute", "Lambda · proactive", [
  "customer wrote in the last 23 hours → free-text WhatsApp",
  "otherwise → approved WhatsApp template",
  "WhatsApp send fails → email through SES",
]);
box(1290, 705, 350, 45, "cds", "WhatsApp update · EUM Social");
box(1290, 765, 350, 45, "cds", "Email fallback · Amazon SES");
arrow("M345,755 H418"); step(382, 740, 7);
arrow("M680,755 H763");
arrow("M1235,727 H1288", { color: C.cds.stroke });
arrow("M1235,787 H1288", { color: C.cds.stroke });

// ---------- footer ----------
out.push(`<rect x="30" y="860" width="1630" height="70" rx="12" fill="#f1f5f9" stroke="#cbd5e1"/>`);
out.push(`<text x="46" y="884" class="sub"><tspan class="b">Cross-cutting:</tspan> AWS CDK (one stack, one-command deploy) · customer-managed AWS KMS key · least-privilege IAM role per function · Amazon CloudWatch Logs · every resource tagged Project / Owner / Purpose / ExpiresAfter</text>`);
const key = [["cds", "AWS CDS service"], ["compute", "Compute and logic"], ["ai", "AI services"], ["data", "Data"], ["events", "Events"], ["people", "People"]];
key.forEach(([k, t], i) => {
  const x = 46 + i * 190;
  out.push(`<rect x="${x}" y="899" width="16" height="16" rx="3" fill="${C[k].fill}" stroke="${C[k].stroke}" stroke-width="1.6"/>`);
  out.push(`<text x="${x + 24}" y="912" class="sub">${esc(t)}</text>`);
});

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Segoe UI, Arial, Helvetica, sans-serif">
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker>
  <marker id="arrowStart" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="context-stroke"/></marker>
  <style>
    .h1{font-size:26px;font-weight:700;fill:#0f172a}
    .h2{font-size:13px;fill:#475569}
    .zone{font-size:12px;font-weight:700;letter-spacing:.06em;fill:#475569}
    .title{font-size:14px;font-weight:700}
    .sub{font-size:12px;fill:#334155}
    .mono{font-size:12px;fill:#334155;font-family:Consolas, monospace}
    .label{font-size:11px;fill:#475569}
    .step{font-size:11px;font-weight:700;fill:#ffffff}
    .b{font-weight:700}
  </style>
</defs>
<rect width="${W}" height="${H}" fill="#ffffff"/>
${out.join("\n")}
</svg>
`;
fs.writeFileSync(path.join(__dirname, "..", "architecture.svg"), svg);
console.log("wrote docs/architecture.svg");
