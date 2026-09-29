"use client";

export default function ErrorPage({reset}: {reset: () => void}) {
  return <main className="center-stage"><div className="error-card"><h1>Dashboard unavailable</h1><p>The API could not be reached.</p><button onClick={reset}>Try again</button></div></main>;
}
