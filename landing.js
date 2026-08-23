/* ====================================================================
   AgriSetu — Landing Page JavaScript
   Handles: Particles, Animations, Auth Modal, Scroll Effects, Sensors
   ==================================================================== */

'use strict';

/* ══════════════════════════════════════════
   1. PARTICLE SYSTEM
══════════════════════════════════════════ */
(function initParticles() {
  const canvas = document.getElementById('particleCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, particles = [];
  const MAX = 70;

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  class Particle {
    constructor() { this.reset(); }
    reset() {
      this.x = Math.random() * W;
      this.y = Math.random() * H;
      this.r = Math.random() * 1.5 + 0.3;
      this.vx = (Math.random() - 0.5) * 0.3;
      this.vy = (Math.random() - 0.5) * 0.3;
      this.alpha = Math.random() * 0.4 + 0.1;
      this.color = Math.random() > 0.5
        ? `rgba(45,212,160,${this.alpha})`
        : `rgba(34,211,238,${this.alpha * 0.6})`;
    }
    update() {
      this.x += this.vx; this.y += this.vy;
      if (this.x < 0 || this.x > W || this.y < 0 || this.y > H) this.reset();
    }
    draw() {
      ctx.save();
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.r, 0, Math.PI * 2);
      ctx.fillStyle = this.color;
      ctx.fill();
      ctx.restore();
    }
  }

  for (let i = 0; i < MAX; i++) particles.push(new Particle());

  function drawConnections() {
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 120) {
          ctx.save();
          ctx.globalAlpha = (1 - dist / 120) * 0.12;
          ctx.strokeStyle = '#2dd4a0';
          ctx.lineWidth = 0.5;
          ctx.beginPath();
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
          ctx.restore();
        }
      }
    }
  }

  function loop() {
    ctx.clearRect(0, 0, W, H);
    drawConnections();
    particles.forEach(p => { p.update(); p.draw(); });
    requestAnimationFrame(loop);
  }
  loop();
})();

/* ══════════════════════════════════════════
   2. NAVBAR SCROLL EFFECT
══════════════════════════════════════════ */
const navbar = document.getElementById('navbar');
const scrollIndicator = document.getElementById('scrollIndicator');

window.addEventListener('scroll', () => {
  const y = window.scrollY;
  navbar.classList.toggle('scrolled', y > 30);
  if (scrollIndicator) scrollIndicator.style.opacity = y > 100 ? '0' : '1';
  updateActiveNavLink();
}, { passive: true });

function updateActiveNavLink() {
  const sections = ['home', 'features', 'about', 'how', 'cta'];
  const links = document.querySelectorAll('.nav-link');
  let current = 'home';
  sections.forEach(id => {
    const el = document.getElementById(id);
    if (el && window.scrollY >= el.offsetTop - 120) current = id;
  });
  links.forEach(link => {
    const href = link.getAttribute('href');
    link.classList.toggle('active', href === '#' + current);
  });
}

/* ══════════════════════════════════════════
   3. HAMBURGER MOBILE MENU
══════════════════════════════════════════ */
const hamburger = document.getElementById('hamburger');
const navLinks = document.getElementById('navLinks');

hamburger && hamburger.addEventListener('click', () => {
  hamburger.classList.toggle('open');
  navLinks.classList.toggle('mobile-open');
});

navLinks && navLinks.addEventListener('click', (e) => {
  if (e.target.classList.contains('nav-link')) {
    hamburger.classList.remove('open');
    navLinks.classList.remove('mobile-open');
  }
});

/* ══════════════════════════════════════════
   4. SCROLL REVEAL (Intersection Observer)
══════════════════════════════════════════ */
const revealObserver = new IntersectionObserver((entries) => {
  entries.forEach((entry, i) => {
    if (entry.isIntersecting) {
      setTimeout(() => entry.target.classList.add('in-view'), i * 80);
      revealObserver.unobserve(entry.target);
    }
  });
}, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

document.querySelectorAll('.reveal').forEach(el => revealObserver.observe(el));

/* ══════════════════════════════════════════
   5. COUNTER ANIMATION (Hero Stats)
══════════════════════════════════════════ */
function animateCounter(el, target, duration = 2000) {
  const isDecimal = target % 1 !== 0;
  const startTime = performance.now();
  function tick(now) {
    const elapsed = now - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const ease = 1 - Math.pow(1 - progress, 3);
    const current = target * ease;
    el.textContent = isDecimal ? current.toFixed(1) : Math.floor(current);
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

const counterObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      document.querySelectorAll('.stat-num').forEach(el => {
        const target = parseFloat(el.dataset.target);
        animateCounter(el, target);
      });
      counterObserver.disconnect();
    }
  });
}, { threshold: 0.5 });

const heroStats = document.getElementById('heroStats');
if (heroStats) counterObserver.observe(heroStats);

/* ══════════════════════════════════════════
   6. LIVE SENSOR SIMULATION
══════════════════════════════════════════ */
const sensorData = {
  soil:  { el: document.getElementById('valSoil'),  base: 67, unit: '%', min: 40, max: 90, card: document.getElementById('cardSoil') },
  temp:  { el: document.getElementById('valTemp'),  base: 28.4, unit: '°C', min: 22, max: 38, card: document.getElementById('cardTemp') },
  hum:   { el: document.getElementById('valHum'),   base: 72, unit: '%', min: 50, max: 95, card: document.getElementById('cardHum') },
  air:   { el: document.getElementById('valAir'),   base: null, unit: '', min: 0, max: 0, card: document.getElementById('cardAir') },
  light: { el: document.getElementById('valLight'), base: 4.2, unit: ' klx', min: 1.0, max: 8.5, card: document.getElementById('cardLight') }
};

const airQualityLevels = ['Excellent', 'Good', 'Good', 'Fair', 'Good', 'Good'];
let airIdx = 1;

function randNoise(val, range) {
  return Math.max(0, val + (Math.random() - 0.5) * range);
}

function updateSensors() {
  if (sensorData.soil.el) {
    const v = randNoise(sensorData.soil.base, 6).toFixed(0);
    sensorData.soil.el.textContent = v + '%';
    const bar = sensorData.soil.card && sensorData.soil.card.querySelector('.sensor-bar-fill');
    if (bar) bar.style.width = Math.min(100, parseInt(v)) + '%';
  }
  if (sensorData.temp.el) {
    const v = randNoise(sensorData.temp.base, 2).toFixed(1);
    sensorData.temp.el.textContent = v + '°C';
    const bar = sensorData.temp.card && sensorData.temp.card.querySelector('.sensor-bar-fill');
    if (bar) bar.style.width = Math.min(100, ((parseFloat(v) - 10) / 30) * 100).toFixed(0) + '%';
  }
  if (sensorData.hum.el) {
    const v = randNoise(sensorData.hum.base, 8).toFixed(0);
    sensorData.hum.el.textContent = v + '%';
    const bar = sensorData.hum.card && sensorData.hum.card.querySelector('.sensor-bar-fill');
    if (bar) bar.style.width = Math.min(100, parseInt(v)) + '%';
  }
  if (sensorData.air.el) {
    airIdx = (airIdx + 1) % airQualityLevels.length;
    sensorData.air.el.textContent = airQualityLevels[airIdx];
  }
  if (sensorData.light.el) {
    const v = randNoise(sensorData.light.base, 1.5).toFixed(1);
    sensorData.light.el.textContent = v + ' klx';
    const bar = sensorData.light.card && sensorData.light.card.querySelector('.sensor-bar-fill');
    if (bar) bar.style.width = Math.min(100, (parseFloat(v) / 10) * 100).toFixed(0) + '%';
  }
}

setInterval(updateSensors, 3000);

/* ══════════════════════════════════════════
   7. ENTER DASHBOARD
══════════════════════════════════════════ */
function enterDashboard() {
  showToast('Welcome to AgriSetu! Loading dashboard…');
  setTimeout(() => {
    window.location.href = 'dashboard/index.html';
  }, 800);
}

// Close on Escape (kept for backward compatibility)
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { /* no-op */ }
});



/* ══════════════════════════════════════════
   10. TOAST NOTIFICATION
══════════════════════════════════════════ */
function showToast(msg, isError = false) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = msg;
  toast.className = 'toast show' + (isError ? ' error' : '');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { toast.classList.remove('show'); }, 3500);
}

/* ══════════════════════════════════════════
   11. SMOOTH SCROLL FOR NAV LINKS
══════════════════════════════════════════ */
document.querySelectorAll('a[href^="#"]').forEach(link => {
  link.addEventListener('click', e => {
    const target = document.querySelector(link.getAttribute('href'));
    if (target) {
      e.preventDefault();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
});

/* ══════════════════════════════════════════
   12. TYPING EFFECT ON TAGLINE
══════════════════════════════════════════ */
(function typeEffect() {
  const el = document.getElementById('taglineDynamic');
  if (!el) return;
  const words = ['Op', 'Think', 'Adapt', 'Learn', 'Optimize'];
  let wIdx = 0, cIdx = 0, deleting = false;

  function tick() {
    const word = words[wIdx];
    if (deleting) {
      cIdx--;
      el.textContent = word.substring(0, cIdx);
      if (cIdx === 0) {
        deleting = false;
        wIdx = (wIdx + 1) % words.length;
        setTimeout(tick, 400);
        return;
      }
    } else {
      cIdx++;
      el.textContent = word.substring(0, cIdx);
      if (cIdx === word.length) {
        setTimeout(() => { deleting = true; tick(); }, 2000);
        return;
      }
    }
    setTimeout(tick, deleting ? 60 : 120);
  }
  setTimeout(tick, 1500);
})();

/* ══════════════════════════════════════════
   13. MOUSE PARALLAX ON HERO VISUAL
══════════════════════════════════════════ */
(function parallax() {
  const visual = document.getElementById('heroVisual');
  if (!visual) return;
  document.addEventListener('mousemove', e => {
    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2;
    const dx = (e.clientX - cx) / cx;
    const dy = (e.clientY - cy) / cy;
    visual.style.transform = `perspective(1000px) rotateY(${dx * 3}deg) rotateX(${-dy * 2}deg)`;
  }, { passive: true });
  document.addEventListener('mouseleave', () => {
    visual.style.transform = 'none';
  });
})();

/* ══════════════════════════════════════════
   14. EXPOSE GLOBAL FUNCTIONS
══════════════════════════════════════════ */
window.enterDashboard = enterDashboard;
