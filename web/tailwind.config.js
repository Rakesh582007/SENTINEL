// Design tokens. Light blue + beige, taken from aeronautical charts:
// sea and sky in light blue, land and chart paper in beige, navy ink,
// chart blue for anything you can press. Orange is reserved for injected
// (simulated) data and nothing else. Map state colours come from
// docs/FRONTEND_HANDOVER.md §7 and are always paired with a word.
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        air: {
          50: '#F1F6FB',
          100: '#DDEAF5',
          200: '#C7DCEE',
          300: '#A7C6E2',
          500: '#4F86C0',
          600: '#1E5AA8',
          700: '#184B8C',
          800: '#143E73',
        },
        sand: {
          50: '#FBF8F1',
          100: '#F6F1E5',
          200: '#ECE3CD',
          300: '#E1D5B8',
          400: '#C8B78F',
          600: '#7A6A47',
        },
        ink: {
          900: '#13294B',
          700: '#2C4467',
          600: '#4B5E78',
          400: '#7D8CA1',
          200: '#C3CCD8',
        },
        signal: {
          50: '#FEEDE2',
          100: '#FCD9C3',
          500: '#F26B1D',
          700: '#B4470C',
          900: '#4A1D05',
        },
        state: {
          clear: '#2EAF6E',
          degraded: '#E8A33C',
          jammed: '#E5484D',
          spoofing: '#9B5DE5',
          insufficient: '#6B7A90',
        },
        sea: '#CFE2F1',
      },
      fontFamily: {
        ui: ['Mukta', 'Segoe UI', 'Noto Sans', 'system-ui', 'sans-serif'],
        data: ['B612', 'Consolas', 'Menlo', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        float: '0 1px 2px rgba(19, 41, 75, 0.10), 0 6px 18px rgba(19, 41, 75, 0.10)',
      },
    },
  },
  plugins: [],
}
