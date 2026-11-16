"""Visual theme for the invoice agent Streamlit app."""

import streamlit as st


CSS = """
<style>

@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=DM+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');

:root {
  --ink:#12163A;
  --ink-2:#1D2354;
  --canvas:#F3F5FB;
  --surface:#FFFFFF;
  --accent:#3340F2;
  --accent-2:#6A4DF5;
  --muted:#444C70;
  --line:#DDE1F0;
  --ok:#12A36B;
  --ok-bg:#E6F6EF;
  --warn:#C98200;
  --warn-bg:#FFF4DC;
  --bad:#D6455D;
}

/* ---------- BACKGROUND ---------- */

[data-testid='stAppViewContainer'] {
  /* Keep Streamlit's native viewport and scroll layout intact. */
  background:
    radial-gradient(900px circle at 100% 0%, rgba(56,189,248,.45), transparent 60%),
    radial-gradient(800px circle at 100% 100%, rgba(168,85,247,.40), transparent 60%),
    radial-gradient(700px circle at 0% 100%, rgba(51,64,242,.28), transparent 60%),
    radial-gradient(600px circle at 0% 0%, rgba(18,163,107,.18), transparent 60%),
    #EEF0FA !important;
}

[data-testid='stAppViewContainer']::before {
  content:'';
  position:fixed;
  inset:-10%;
  z-index:0;
  pointer-events:none;
  background:
    radial-gradient(ellipse 45% 40% at 10% 15%, rgba(51,64,242,.28), transparent 70%),
    radial-gradient(ellipse 40% 35% at 90% 10%, rgba(0,170,220,.26), transparent 70%),
    radial-gradient(ellipse 45% 40% at 85% 90%, rgba(150,90,255,.28), transparent 70%),
    radial-gradient(ellipse 40% 35% at 10% 95%, rgba(18,163,107,.14), transparent 70%);
  animation:drift 24s ease-in-out infinite alternate;
}

[data-testid='stAppViewContainer']::after {
  content:'';
  position:fixed;
  inset:0;
  z-index:0;
  pointer-events:none;
  background-image:radial-gradient(rgba(51,64,242,.45) 1.6px, transparent 1.6px);
  background-size:28px 28px;
  -webkit-mask-image:radial-gradient(ellipse at 75% 50%, #000 15%, transparent 70%);
  mask-image:radial-gradient(ellipse at 75% 50%, #000 15%, transparent 70%);
}

[data-testid='stMain']::before {
  content:'';
  position:fixed;
  top:20%;
  right:4%;
  width:520px;
  height:520px;
  z-index:-1;
  pointer-events:none;
  border-radius:50%;
  background:radial-gradient(circle, rgba(106,77,245,.60), rgba(56,189,248,.25) 55%, transparent 72%);
  filter:blur(60px);
  animation:blob 16s ease-in-out infinite alternate;
}

@keyframes drift {
  from { transform:translate3d(-2%,-1%,0) scale(1); }
  to { transform:translate3d(2%,2%,0) scale(1.05); }
}

@keyframes blob {
  from { transform:translate(0,0) scale(1); }
  to { transform:translate(-90px,60px) scale(1.2); }
}

/* Keep content above decorative background.
   Let Streamlit manage page and sidebar scrolling naturally. */

[data-testid='stMain'],
[data-testid='stHeader'] {
  position:relative;
  z-index:1;
}

[data-testid='stSidebar'] {
  z-index:3;
}

[data-testid='stMain'],
[data-testid='stMainBlockContainer'] {
  background:transparent !important;
}

[data-testid='stHeader'] {
  background:transparent !important;
}

[data-testid='stAppDeployButton'],
.stDeployButton,
footer {
  display:none !important;
}

.block-container {
  max-width:1480px;
  /* Extra end space lets the final cards/expanders scroll fully into view. */
  padding:1.2rem 2rem 6rem;
}

/* Preserve normal vertical scrolling in Streamlit's main content area. */
[data-testid='stMain'] {
  overflow-y:auto !important;
  overflow-x:hidden !important;
}

[data-testid='stMainBlockContainer'] {
  min-height:max-content !important;
}


/* ---------- TYPOGRAPHY ---------- */

.stApp,
.stApp p,
.stApp label,
.stApp li,
.stApp input,
.stApp textarea,
.stApp button,
[data-testid='stCaptionContainer'] {
  font-family:'DM Sans',system-ui,sans-serif;
}

h1, h2, h3, h4 {
  font-family:'Bricolage Grotesque','DM Sans',sans-serif !important;
  color:var(--ink);
  letter-spacing:-.03em;
}

h1 {
  font-weight:800 !important;
}

h2, h3 {
  font-weight:600 !important;
}

[data-testid='stCaptionContainer'],
[data-testid='stCaptionContainer'] * {
  color:#3B4366 !important;
  opacity:1 !important;
}

input::placeholder,
textarea::placeholder {
  color:#6B7394 !important;
  opacity:1 !important;
}

.page-eyebrow {
  display:inline-block;
  font-size:.82rem;
  font-weight:600;
  color:var(--accent);
  background:rgba(51,64,242,.09);
  padding:4px 12px;
  border-radius:999px;
  text-transform:lowercase;
  margin-bottom:6px;
}

.page-eyebrow::first-letter {
  text-transform:uppercase;
}


/* ---------- CARDS, METRICS, TABS ---------- */

[data-testid='stVerticalBlockBorderWrapper'] {
  background:rgba(255,255,255,.82) !important;
  border:1px solid var(--line) !important;
  border-radius:16px !important;
  box-shadow:0 8px 28px rgba(18,22,58,.06);
  backdrop-filter:blur(14px);
}

[data-testid='stMetric'] {
  background:var(--surface);
  border:1px solid var(--line);
  border-left:4px solid var(--accent);
  border-radius:14px;
  padding:16px 18px;
  box-shadow:0 4px 18px rgba(18,22,58,.05);
}

[data-testid='stMetricValue'] {
  font-family:'Bricolage Grotesque',sans-serif;
  font-weight:800;
  color:var(--ink);
}

[data-baseweb='tab-list'] {
  gap:6px;
  background:rgba(18,22,58,.06);
  padding:5px;
  border-radius:12px;
  width:fit-content;
}

button[data-baseweb='tab'] {
  border-radius:9px;
  padding:8px 16px;
  height:auto;
}

button[data-baseweb='tab'][aria-selected='true'] {
  background:var(--surface);
  box-shadow:0 2px 8px rgba(18,22,58,.10);
  color:var(--accent);
  font-weight:600;
}

[data-baseweb='tab-highlight'],
[data-baseweb='tab-border'] {
  display:none;
}

[data-testid='stAlert'] {
  border-radius:12px;
  border:1px solid var(--line);
}

[data-testid='stExpander'] {
  border:1px solid var(--line) !important;
  border-radius:12px;
  background:rgba(255,255,255,.7);
}

[data-testid='stDataFrame'] {
  border:1px solid var(--line);
  border-radius:12px;
  overflow:hidden;
}


/* ---------- INPUTS AND UPLOADER ---------- */

div[data-baseweb='input'] > div,
div[data-baseweb='select'] > div,
div[data-baseweb='textarea'] {
  background:#fff;
  border-radius:11px;
  border:1px solid var(--line);
}

div[data-baseweb='input']:focus-within > div {
  border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(51,64,242,.15);
}

[data-testid='stFileUploaderDropzone'] {
  background:rgba(51,64,242,.04);
  border:2px dashed rgba(51,64,242,.35);
  border-radius:14px;
  padding:30px;
  transition:border-color .2s, background .2s;
}

[data-testid='stFileUploaderDropzone']:hover {
  border-color:var(--accent);
  background:rgba(51,64,242,.08);
}

div[data-testid='stForm'] {
  background:rgba(255,255,255,.66);
  -webkit-backdrop-filter:blur(16px);
  backdrop-filter:blur(16px);
  border:1px solid rgba(255,255,255,.85);
  border-radius:20px;
  padding:28px;
  box-shadow:0 20px 60px rgba(51,64,242,.14);
}


/* ---------- BUTTONS ---------- */

button[kind='primary'],
[data-testid='stBaseButton-primary'],
[data-testid='stBaseButton-primaryFormSubmit'] {
  background:linear-gradient(135deg,var(--accent),var(--accent-2)) !important;
  color:#fff !important;
  border:none !important;
  border-radius:11px !important;
  font-weight:600 !important;
  min-height:44px;
  box-shadow:0 6px 18px rgba(51,64,242,.28);
  transition:transform .15s, box-shadow .15s;
}

button[kind='primary']:hover,
[data-testid='stBaseButton-primary']:hover,
[data-testid='stBaseButton-primaryFormSubmit']:hover {
  transform:translateY(-2px);
  box-shadow:0 12px 28px rgba(51,64,242,.40);
}

[data-testid='stBaseButton-secondary'] {
  background:#fff;
  border:1px solid var(--line);
  border-radius:11px;
  min-height:44px;
  font-weight:600;
}

[data-testid='stBaseButton-secondary']:hover {
  border-color:var(--accent);
  color:var(--accent);
}


/* ---------- SIDEBAR ---------- */

[data-testid='stSidebar'] {
  background:var(--ink) !important;
  border-right:1px solid #232A5E;
}

[data-testid='stSidebar'] [data-testid='stMarkdownContainer'] * {
  color:#F4F5FF !important;
}

[data-testid='stSidebar'] [data-testid='stCaptionContainer'] {
  color:#9AA3D6 !important;
}

[data-testid='stSidebar'] [data-testid='stCaptionContainer'] p {
  color:#9AA3D6 !important;
}

[data-testid='stSidebar'] hr {
  border-color:rgba(255,255,255,.12);
}

[data-testid='stSidebar'] button {
  background:rgba(255,255,255,.07) !important;
  color:#fff !important;
  border:1px solid rgba(255,255,255,.16) !important;
  border-radius:11px;
  box-shadow:none !important;
}

[data-testid='stSidebar'] button:hover {
  background:rgba(255,255,255,.14) !important;
}


/* ---------- UPLOAD PAGE HELPERS ---------- */

.upload-step {
  background:#fff;
  border:1px solid var(--line);
  border-left:4px solid var(--accent);
  border-radius:12px;
  padding:12px 16px;
}

.upload-step small {
  color:var(--muted);
}


/* ---------- LOGIN ---------- */

.login-label {
  font-weight:600;
  color:var(--accent);
  font-size:.9rem;
}

[data-testid='stHorizontalBlock']:has(.login-hero) {
  align-items:center;
}

.login-hero {
  position:relative;
  overflow:hidden;
  border-radius:26px;
  padding:40px;
  min-height:560px;
  color:#fff;
  background:
    radial-gradient(circle at 88% 0%, rgba(106,77,245,.55), transparent 50%),
    linear-gradient(150deg,var(--ink),var(--ink-2) 70%);
  box-shadow:0 24px 60px rgba(18,22,58,.28);
}

.login-hero .brand {
  display:flex;
  align-items:center;
  gap:10px;
  font-weight:600;
  color:#C9CEFF;
  margin-bottom:34px;
}

.login-hero h1 {
  color:#fff !important;
  font-size:2.6rem;
  line-height:1.06;
  font-weight:800;
  letter-spacing:-.035em;
  margin:0 0 16px;
  padding:0;
}

.login-hero .description {
  color:#B9BFE8;
  max-width:46ch;
  line-height:1.6;
  margin-bottom:32px;
}

.ticket {
  background:#fff;
  color:var(--ink);
  border-radius:16px;
  padding:20px 22px;
  max-width:520px;
  box-shadow:0 18px 40px rgba(0,0,0,.30);
  transform:rotate(-1.2deg);
  animation:float 6s ease-in-out infinite alternate;
}

@keyframes float {
  from { transform:translateY(0) rotate(-1.2deg); }
  to { transform:translateY(-8px) rotate(-.6deg); }
}

.ticket-head {
  display:flex;
  justify-content:space-between;
  align-items:flex-start;
  padding-bottom:14px;
  margin-bottom:8px;
  border-bottom:1px dashed var(--line);
}

.ticket-vendor {
  font-weight:700;
}

.ticket-ref {
  font-family:'IBM Plex Mono',monospace;
  font-size:.8rem;
  color:var(--muted);
  display:flex;
  gap:12px;
}

.ticket-total {
  font-family:'IBM Plex Mono',monospace;
  font-weight:500;
  font-size:1.25rem;
}

.check {
  display:flex;
  align-items:center;
  gap:12px;
  padding:9px 0;
  font-size:.93rem;
  opacity:0;
  transform:translateY(6px);
  animation:checkIn .5s ease forwards;
}

.ticket .check:nth-child(2) { animation-delay:.6s; }
.ticket .check:nth-child(3) { animation-delay:1.2s; }
.ticket .check:nth-child(4) { animation-delay:1.8s; }
.ticket .check:nth-child(5) { animation-delay:2.6s; }

.tick {
  flex:none;
  width:22px;
  height:22px;
  border-radius:50%;
  background:var(--ok);
  color:#fff;
  display:grid;
  place-items:center;
  font-size:.8rem;
  font-weight:700;
}

.check.hold {
  margin-top:6px;
  padding:12px 14px;
  border-radius:10px;
  background:var(--warn-bg);
  color:#7A5200;
  font-weight:600;
}

.check.hold .tick {
  background:var(--warn);
}

@keyframes checkIn {
  to {
    opacity:1;
    transform:none;
  }
}

.login-footer {
  display:flex;
  align-items:center;
  gap:8px;
  margin-top:14px;
  font-size:.88rem;
  font-weight:500;
  color:var(--muted);
}


/* ---------- RESPONSIVE ---------- */

@media (max-width:900px) {
  .login-hero {
    min-height:0;
    padding:28px;
  }

  .login-hero h1 {
    font-size:2rem;
  }

  .block-container {
    padding:1rem;
  }

  [data-testid='stMain']::before {
    display:none;
  }
}

@media (prefers-reduced-motion: reduce) {
  [data-testid='stAppViewContainer']::before,
  [data-testid='stMain']::before,
  .ticket {
    animation:none;
  }

  .check {
    animation:none;
    opacity:1;
    transform:none;
  }
}

</style>
"""


LOGIN_HERO_HTML = """
<div class="login-hero">
  <div class="brand">🧾 Invoice agent</div>
  <h1>The AI checks the invoice.<br>A person approves the payment.</h1>
  <div class="description">
    Upload an invoice and the agent reads it, checks the arithmetic, finds the
    purchase order and confirms the vendor. Nothing is paid until an approver signs off.
  </div>
  <div class="ticket">
    <div class="ticket-head">
      <div>
        <div class="ticket-vendor">Northwind Supply Co.</div>
        <div class="ticket-ref"><span>INV-2041</span><span>PO-7731</span></div>
      </div>
      <div class="ticket-total">4,860.00</div>
    </div>
    <div class="check"><span class="tick">✓</span><span>Line items add up to the total</span></div>
    <div class="check"><span class="tick">✓</span><span>Purchase order found</span></div>
    <div class="check"><span class="tick">✓</span><span>Vendor matches the purchase order</span></div>
    <div class="check hold"><span class="tick">!</span><span>Waiting for an approver</span></div>
  </div>
</div>
"""


LOGIN_FOOTER_HTML = """
<div class="login-footer">
  🔒 <span>Human approval required for every payment</span>
</div>
"""


def inject_theme():
    st.markdown(CSS, unsafe_allow_html=True)