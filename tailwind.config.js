/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: {
          DEFAULT: '#0a0a0a',
          card: '#191919',
          soft: '#1a1c20',
          hover: '#24262b'
        },
        ink: {
          DEFAULT: '#ffffff',
          body: '#dadbdf',
          mute: '#7d8187'
        },
        hairline: {
          DEFAULT: '#212327',
          light: '#2a2d33',
          bright: '#3d414a'
        },
        accent: {
          sunset: '#ff7a17',
          sunsetsoft: 'rgba(255, 122, 23, 0.15)'
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['Geist Mono', 'JetBrains Mono', 'Fira Code', 'monospace']
      },
      letterSpacing: {
        tightest: '-0.05em',
        tighter: '-0.03em',
        tight: '-0.015em',
        widestmono: '0.2em'
      }
    },
  },
  plugins: [],
}
