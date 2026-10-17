import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import ResponderView from './ResponderView.jsx'

const responderRoute = window.location.pathname.match(/^\/demo\/responder\/(\d+)$/)

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {responderRoute ? <ResponderView eventId={responderRoute[1]} /> : <App />}
  </StrictMode>,
)
