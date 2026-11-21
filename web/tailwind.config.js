/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'rgb(var(--canvas) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-muted': 'rgb(var(--surface-muted) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        'ink-muted': 'rgb(var(--ink-muted) / <alpha-value>)',
        accent: 'rgb(var(--accent) / <alpha-value>)',
        'accent-soft': 'rgb(var(--accent-soft) / <alpha-value>)',
        citation: 'rgb(var(--citation) / <alpha-value>)',
        'citation-soft': 'rgb(var(--citation-soft) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
        danger: 'rgb(var(--danger) / <alpha-value>)',
      },
      fontFamily: {
        sans: [
          'ui-sans-serif',
          '-apple-system',
          'Segoe UI',
          'PingFang SC',
          'Microsoft YaHei',
          'Noto Sans SC',
          'sans-serif',
        ],
        serif: ['Georgia', 'Noto Serif SC', 'Songti SC', 'serif'],
        mono: ['ui-monospace', 'Consolas', 'JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        subtle: '0 1px 2px rgb(16 24 40 / 0.04)',
        floating: '0 12px 32px rgb(16 24 40 / 0.12)',
      },
      borderRadius: {
        card: '12px',
        panel: '16px',
      },
    },
  },
  plugins: [],
}