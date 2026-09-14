// SSE topics the backend accepts (events.TOPICS + parameterised prefixes).
export const TOPICS = ['nowplaying', 'queue', 'health', 'relay', 'obs', 'downloads',
  'update', 'netscan', 'dice', 'scene', 'server', 'producer'];
export const PARAM_PREFIXES = ['battlemap:', 'session:', 'character:', 'syncjob:', 'aijob:'];
export function topicOk(t) { return TOPICS.includes(t) || PARAM_PREFIXES.some(p => t.startsWith(p)); }
