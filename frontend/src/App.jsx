import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from 'react-router-dom'
import Home from './pages/Home'
import Callback from './pages/Callback'
import Dashboard from './pages/Dashboard'
import { readSessionToken, storeSessionToken } from './utils/auth'

function PrivateRoute({ children }) {
  // Check URL for token first (coming from OAuth redirect). The query string is
  // attacker-controllable, so the value is shape-checked before it is persisted
  // -- see utils/auth.js.
  const params = new URLSearchParams(window.location.search)
  storeSessionToken(params.get('token'))

  const token = readSessionToken()
  return token ? children : <Navigate to="/" replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/callback" element={<Callback />} />
        <Route path="/dashboard" element={
          <PrivateRoute>
            <Dashboard />
          </PrivateRoute>
        } />
      </Routes>
    </BrowserRouter>
  )
}