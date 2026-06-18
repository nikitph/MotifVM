const canvas = document.getElementById("kernel-canvas");
const ctx = canvas.getContext("2d");
const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let width = 0;
let height = 0;
let nodes = [];

const stages = [
  "TaskAST",
  "MotifFrame",
  "ReasoningPlan",
  "StatePatch",
  "Invariant",
  "Replan",
  "AuditPack"
];

function resize() {
  const ratio = window.devicePixelRatio || 1;
  width = canvas.clientWidth;
  height = canvas.clientHeight;
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  buildNodes();
}

function buildNodes() {
  const columns = stages.length;
  const top = height * 0.22;
  const bottom = height * 0.76;
  nodes = stages.map((label, index) => {
    const x = width * (0.42 + (index / (columns - 1)) * 0.52);
    const y = top + ((index % 2) * 0.42 + 0.14) * (bottom - top);
    return {
      label,
      x,
      y,
      r: index === 2 ? 18 : 13,
      phase: index * 0.8,
      color: ["#1769c2", "#0d8a72", "#7154cf", "#a66b00", "#c73652", "#0d8a72", "#334155"][index]
    };
  });
}

function draw(time = 0) {
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "#fffaf0");
  gradient.addColorStop(0.55, "#f6f3ed");
  gradient.addColorStop(1, "#eef5f6");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  const t = time * 0.001;
  ctx.lineWidth = 1;
  for (let i = 0; i < nodes.length - 1; i += 1) {
    const a = nodes[i];
    const b = nodes[i + 1];
    const pulse = prefersReduced ? 0.4 : (Math.sin(t * 1.6 + i) + 1) / 2;
    ctx.strokeStyle = `rgba(23, 105, 194, ${0.12 + pulse * 0.22})`;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    const mid = (a.x + b.x) / 2;
    ctx.bezierCurveTo(mid, a.y, mid, b.y, b.x, b.y);
    ctx.stroke();
  }

  for (const node of nodes) {
    const pulse = prefersReduced ? 0 : Math.sin(t * 1.8 + node.phase) * 2.6;
    ctx.beginPath();
    ctx.fillStyle = "rgba(23, 105, 194, 0.06)";
    ctx.arc(node.x, node.y, node.r + 18 + pulse, 0, Math.PI * 2);
    ctx.fill();

    ctx.beginPath();
    ctx.fillStyle = node.color;
    ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
    ctx.fill();

    ctx.font = "760 13px Aptos, Inter, system-ui, sans-serif";
    ctx.fillStyle = "rgba(23, 32, 42, 0.76)";
    ctx.textAlign = "center";
    ctx.fillText(node.label, node.x, node.y + node.r + 28);
  }

  drawStateMachine(t);

  if (!prefersReduced) {
    requestAnimationFrame(draw);
  }
}

function drawStateMachine(t) {
  const x = width * 0.69;
  const y = height * 0.5;
  const radius = Math.min(width, height) * 0.19;
  const labels = ["validate", "authorize", "apply", "verify", "commit"];
  ctx.strokeStyle = "rgba(13, 138, 114, 0.22)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.stroke();

  labels.forEach((label, index) => {
    const angle = (Math.PI * 2 * index) / labels.length - Math.PI / 2 + (prefersReduced ? 0 : t * 0.035);
    const px = x + Math.cos(angle) * radius;
    const py = y + Math.sin(angle) * radius;
    ctx.fillStyle = "rgba(255, 255, 255, 0.82)";
    ctx.strokeStyle = "rgba(23, 32, 42, 0.14)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.rect(px - 46, py - 15, 92, 30);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = "rgba(23, 32, 42, 0.82)";
    ctx.font = "760 11px Aptos, Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(label, px, py + 4);
  });
}

window.addEventListener("resize", resize);
resize();
draw();
