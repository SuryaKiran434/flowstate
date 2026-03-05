import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from 'react-router-dom'
import Home from './pages/Home'
import Callback from './pages/Callback'
import Dashboard from './pages/Dashboard'

function PrivateRoute({ children }) {
  // Check URL for token first (coming from OAuth redirect)
  const params = new URLSearchParams(window.location.search)
  const tokenFromUrl = params.get('token')
  if (tokenFromUrl) {
    localStorage.setItem('flowstate_token', tokenFromUrl)
  }

  const token = localStorage.getItem('flowstate_token')
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