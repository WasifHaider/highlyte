// Only follow ?next= to a path on this site, never to another domain
// (an open redirect a phishing link could use).
export function safeNext(next) {
  return typeof next === 'string' && next.startsWith('/') && !next.startsWith('//') ? next : '/'
}
