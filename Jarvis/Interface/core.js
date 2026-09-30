// Réacteur central du HUD : anneaux concentriques animés qui réagissent à la voix.

const TAU = Math.PI * 2;
const BARS = 96;

// Couleur, intensité lumineuse et vitesse de rotation de chaque état.
const STATES = {
  offline:   { color: [92, 112, 132],  glow: 0.22, spin: 0.12 },
  idle:      { color: [56, 196, 255],  glow: 0.55, spin: 0.32 },
  listening: { color: [150, 238, 255], glow: 0.95, spin: 0.62 },
  thinking:  { color: [255, 192, 84],  glow: 0.85, spin: 2.3 },
  speaking:  { color: [92, 222, 255],  glow: 1.0,  spin: 0.85 },
  alert:     { color: [255, 98, 82],   glow: 1.0,  spin: 1.5 },
};

export class ReactorCore {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.state = 'offline';
    this.color = [...STATES.offline.color];
    this.glow = STATES.offline.glow;
    this.spin = STATES.offline.spin;
    this.angle = 0;
    this.level = 0;
    this.bars = new Float32Array(BARS);
    this.levelSource = null;
    this.lastTime = 0;
    this.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    new ResizeObserver(() => this.resize()).observe(canvas);
    this.resize();
  }

  setState(state) {
    if (STATES[state]) this.state = state;
  }

  // fn() doit renvoyer { level: 0..1, bins: tableau de 0..1 (ou null) }.
  setLevelSource(fn) {
    this.levelSource = fn;
  }

  resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    this.width = Math.max(1, rect.width);
    this.height = Math.max(1, rect.height);
    this.canvas.width = Math.round(this.width * ratio);
    this.canvas.height = Math.round(this.height * ratio);
    this.ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  start() {
    const frame = (time) => {
      const dt = Math.min(0.05, (time - this.lastTime) / 1000 || 0.016);
      this.lastTime = time;
      this.update(dt, time / 1000);
      this.draw(time / 1000);
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  }

  update(dt, time) {
    const target = STATES[this.state];
    const ease = 1 - Math.exp(-dt * 5);
    for (let i = 0; i < 3; i++) this.color[i] += (target.color[i] - this.color[i]) * ease;
    this.glow += (target.glow - this.glow) * ease;
    this.spin += (target.spin - this.spin) * ease;
    if (!this.reducedMotion) this.angle += this.spin * dt;

    const sample = this.levelSource ? this.levelSource() : null;
    const level = sample ? Math.min(1, sample.level) : 0;
    this.level += (level - this.level) * (1 - Math.exp(-dt * 14));

    const bins = sample && sample.bins;
    for (let i = 0; i < BARS; i++) {
      let value;
      if (bins && bins.length) {
        // Le spectre est replié en miroir pour dessiner un anneau symétrique. Seul le bas
        // du spectre est utilisé : c'est là que se concentre l'énergie de la voix.
        const half = i < BARS / 2 ? i : BARS - 1 - i;
        value = bins[Math.floor((half / (BARS / 2)) * bins.length * 0.24)] || 0;
      } else {
        // Sans signal, l'anneau « respire » doucement.
        value = 0.05 + 0.04 * Math.sin(time * 1.6 + i * 0.4) + this.level * (0.3 + 0.25 * Math.sin(time * 9 + i * 1.7));
      }
      this.bars[i] += (value - this.bars[i]) * (1 - Math.exp(-dt * 18));
    }
  }

  rgba(alpha) {
    const [r, g, b] = this.color;
    return `rgba(${r | 0}, ${g | 0}, ${b | 0}, ${Math.max(0, Math.min(1, alpha))})`;
  }

  arc(radius, start, end, width, alpha) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.arc(0, 0, radius, start, end);
    ctx.lineWidth = width;
    ctx.strokeStyle = this.rgba(alpha);
    ctx.stroke();
  }

  draw(time) {
    const ctx = this.ctx;
    const R = (Math.min(this.width, this.height) / 2) * 0.95;
    const a = this.angle;
    const glow = this.glow;
    const level = this.level;

    ctx.clearRect(0, 0, this.width, this.height);
    ctx.save();
    ctx.translate(this.width / 2, this.height / 2);
    ctx.lineCap = 'butt';

    // Halo
    const halo = ctx.createRadialGradient(0, 0, R * 0.12, 0, 0, R);
    halo.addColorStop(0, this.rgba(0.2 * glow + 0.3 * level));
    halo.addColorStop(0.5, this.rgba(0.06 * glow));
    halo.addColorStop(1, this.rgba(0));
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(0, 0, R, 0, TAU);
    ctx.fill();

    ctx.shadowColor = this.rgba(0.9);
    ctx.shadowBlur = 10 * glow;

    // 1. Couronne graduée
    ctx.save();
    ctx.rotate(a * 0.12);
    for (let i = 0; i < 120; i++) {
      const major = i % 10 === 0;
      const mid = i % 5 === 0;
      const inner = R * (major ? 0.935 : mid ? 0.955 : 0.968);
      ctx.beginPath();
      ctx.moveTo(inner, 0);
      ctx.lineTo(R * 0.985, 0);
      ctx.lineWidth = major ? 2 : 1;
      ctx.strokeStyle = this.rgba(major ? 0.8 : mid ? 0.5 : 0.26);
      ctx.stroke();
      ctx.rotate(TAU / 120);
    }
    ctx.restore();

    // 2. Trois grands arcs
    ctx.save();
    ctx.rotate(a * 0.5);
    for (let i = 0; i < 3; i++) {
      const start = (i * TAU) / 3;
      this.arc(R * 0.885, start, start + TAU / 3 - 0.35, 3, 0.85 * glow + 0.1);
      this.arc(R * 0.86, start + 0.12, start + 0.62, 1.5, 0.45);
    }
    ctx.restore();

    // 3. Anneau pointillé, en sens inverse
    ctx.save();
    ctx.rotate(-a * 0.8);
    ctx.setLineDash([R * 0.012, R * 0.03]);
    this.arc(R * 0.8, 0, TAU, 2, 0.5);
    ctx.setLineDash([]);
    this.arc(R * 0.775, 0.4, 1.9, 5, 0.32);
    this.arc(R * 0.775, 3.5, 5.0, 5, 0.32);
    ctx.restore();

    // 4. Anneau d'énergie segmenté
    ctx.save();
    ctx.rotate(a * 0.28);
    const segments = 30;
    const chase = (time * 8) % segments;
    for (let i = 0; i < segments; i++) {
      const start = (i * TAU) / segments;
      const distance = Math.min(Math.abs(i - chase), segments - Math.abs(i - chase));
      const lit = Math.max(0, 1 - distance / 5);
      this.arc(R * 0.7, start + 0.025, start + TAU / segments - 0.025, R * 0.05, 0.12 + 0.55 * lit * glow + 0.25 * level);
    }
    ctx.restore();

    // Balayage pendant la réflexion
    if (this.state === 'thinking') {
      ctx.save();
      ctx.rotate(a * 1.6);
      const sweep = ctx.createConicGradient ? ctx.createConicGradient(0, 0, 0) : null;
      if (sweep) {
        sweep.addColorStop(0, this.rgba(0));
        sweep.addColorStop(0.2, this.rgba(0.55));
        sweep.addColorStop(0.21, this.rgba(0));
        sweep.addColorStop(1, this.rgba(0));
        ctx.strokeStyle = sweep;
        ctx.lineWidth = R * 0.2;
        ctx.beginPath();
        ctx.arc(0, 0, R * 0.78, 0, TAU);
        ctx.stroke();
      }
      ctx.restore();
    }

    // 5. Spectre circulaire : il suit la voix (micro ou synthèse)
    ctx.save();
    ctx.rotate(-Math.PI / 2);
    const base = R * 0.47;
    const reach = R * 0.17;
    ctx.lineWidth = Math.max(1.5, (TAU * base) / BARS * 0.5);
    for (let i = 0; i < BARS; i++) {
      const value = Math.min(1, this.bars[i]);
      ctx.beginPath();
      ctx.moveTo(base, 0);
      ctx.lineTo(base + 3 + value * reach, 0);
      ctx.strokeStyle = this.rgba(0.35 + 0.65 * value);
      ctx.stroke();
      ctx.rotate(TAU / BARS);
    }
    ctx.restore();

    // 6. Cercle intérieur et repères cardinaux
    this.arc(R * 0.44, 0, TAU, 1.5, 0.7);
    this.arc(R * 0.4, 0, TAU, 1, 0.3);
    ctx.save();
    ctx.rotate(-a * 0.35);
    for (let i = 0; i < 4; i++) {
      this.arc(R * 0.42, (i * TAU) / 4 - 0.16, (i * TAU) / 4 + 0.16, 5, 0.85);
    }
    ctx.restore();

    // 7. Cœur lumineux
    ctx.shadowBlur = 0;
    const pulse = 1 + 0.035 * Math.sin(time * 2.2) + 0.12 * level;
    const heart = ctx.createRadialGradient(0, 0, 0, 0, 0, R * 0.38 * pulse);
    heart.addColorStop(0, this.rgba(0.34 * glow + 0.4 * level));
    heart.addColorStop(0.55, this.rgba(0.12 * glow + 0.12 * level));
    heart.addColorStop(1, this.rgba(0));
    ctx.fillStyle = heart;
    ctx.beginPath();
    ctx.arc(0, 0, R * 0.38 * pulse, 0, TAU);
    ctx.fill();

    ctx.restore();
  }
}
