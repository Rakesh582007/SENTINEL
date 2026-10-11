import React from 'react'
import { createRoot } from 'react-dom/client'
import '@fontsource/mukta/latin-400.css'
import '@fontsource/mukta/latin-500.css'
import '@fontsource/mukta/latin-600.css'
import '@fontsource/mukta/latin-700.css'
import '@fontsource/b612/latin-400.css'
import '@fontsource/b612/latin-700.css'
import 'leaflet/dist/leaflet.css'
import './index.css'
import App from './App.jsx'
import { useStore } from './store.js'

// Handy in the browser console while developing: __sentinel.getState()
if (import.meta.env.DEV) window.__sentinel = useStore

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
