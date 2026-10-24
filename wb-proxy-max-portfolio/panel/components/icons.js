/*
 * panel/components/icons.js —— 线性 SVG 图标库（本地自研，上游无对应）
 *
 * 与导航/卡片同一线性语言，stroke=currentColor，尺寸由 CSS 控制。
 * 图标是纯展示件，不含任何业务语义。
 */
const S = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';

export const BRAND_SVG =
  '<svg viewBox="0 0 24 24" fill="none"><path d="M12 2L21 7v10l-9 5-9-5V7l9-5z" stroke="#04121a" stroke-width="2" stroke-linejoin="round"/><path d="M12 22V12M12 12L21 7M12 12L3 7" stroke="#04121a" stroke-width="2" stroke-linejoin="round"/></svg>';

const ICONS = {
  gateway: `<svg ${S}><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><circle cx="7" cy="7.5" r="1" fill="currentColor" stroke="none"/><circle cx="7" cy="16.5" r="1" fill="currentColor" stroke="none"/></svg>`,
  chart: `<svg ${S}><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>`,
  tasks: `<svg ${S}><path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h9"/></svg>`,
  logs: `<svg ${S}><path d="M4 6h16M4 12h16M4 18h10"/></svg>`,
  settings: `<svg ${S}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33h0a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51h0a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82v0a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
  pool: `<svg ${S}><path d="M17 21v-2a4 4 0 00-4-4H7a4 4 0 00-4 4v2"/><circle cx="10" cy="7" r="3"/><path d="M21 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>`,
  coin: `<svg ${S}><circle cx="12" cy="12" r="9"/><path d="M8.5 9.5l3.5 4 3.5-4M12 13.5V17"/></svg>`,
  pulse: `<svg ${S}><path d="M3 12h4l2.5-7 4 14 2.5-7h5"/></svg>`,
  shield: `<svg ${S}><path d="M12 3l7 3v5c0 4.5-3 8.2-7 10-4-1.8-7-5.5-7-10V6l7-3z"/><path d="M9.5 12l2 2 3.5-4"/></svg>`,
  calendar: `<svg ${S}><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M8 3v4M16 3v4M9 14l2 2 4-4"/></svg>`,
  send: `<svg ${S}><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>`,
  radio: `<svg ${S}><circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 010 8.49M7.76 16.24a6 6 0 010-8.49M19.07 4.93a10 10 0 010 14.14M4.93 19.07a10 10 0 010-14.14"/></svg>`,
  moon: `<svg ${S}><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>`,
  cap: `<svg ${S}><path d="M22 10L12 5 2 10l10 5 10-5z"/><path d="M6 12v5c0 1.5 2.7 3 6 3s6-1.5 6-3v-5"/><path d="M22 10v6"/></svg>`,
  refresh: `<svg ${S}><path d="M21 12a9 9 0 11-2.64-6.36"/><path d="M21 3v6h-6"/></svg>`,
  gem: `<svg ${S}><path d="M6 3h12l4 6-10 12L2 9l4-6z"/><path d="M2 9h20M12 3l-3 6 3 12 3-12-3-6z"/></svg>`,
  bolt: `<svg ${S}><path d="M13 2L4.5 13.5H11L10 22l8.5-11.5H13L13 2z"/></svg>`,
  db: `<svg ${S}><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.66 3.58 3 8 3s8-1.34 8-3V5"/><path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3"/></svg>`,
  cat: `<svg ${S}><circle cx="5.5" cy="6" r="1.4"/><circle cx="9.5" cy="4.4" r="1.4"/><circle cx="14.5" cy="4.4" r="1.4"/><circle cx="18.5" cy="6" r="1.4"/><path d="M12 10c-2.8 0-5 2.2-5 5a5 5 0 005 5 5 5 0 005-5c0-2.8-2.2-5-5-5z"/></svg>`,
  user: `<svg ${S}><circle cx="9.5" cy="8" r="3.6"/><path d="M3 19.2c.9-3.2 3.4-5 6.5-5s5.6 1.8 6.5 5"/><path d="M18.5 7.5v6M15.5 10.5h6"/></svg>`,
  layers: `<svg ${S}><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5M2 12l10 5 10-5"/></svg>`,
  key: `<svg ${S}><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`,
  clock: `<svg ${S}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>`,
  /* palette 取自原 App.js 内联的导航图标原文 */
  palette: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="13.5" cy="6.5" r="1.5"/><circle cx="17.5" cy="10.5" r="1.5"/><circle cx="8.5" cy="7.5" r="1.5"/><circle cx="6.5" cy="12.5" r="1.5"/><path d="M12 2a10 10 0 100 20c1.1 0 2-.9 2-2 0-.61-.23-1.15-.6-1.57-.36-.41-.6-.95-.6-1.43a2 2 0 012-2h2.4c1.55 0 2.8-1.25 2.8-2.8A10 10 0 0012 2z"/></svg>`,
  logout: `<svg ${S}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>`,
};

export function ico(name) {
  return ICONS[name] || "";
}

export default ico;
