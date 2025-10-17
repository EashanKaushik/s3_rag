import { useChat } from '../hooks/useChat'

export function Sidebar() {
  const { sessionId, agentArn, agentCards } = useChat()

  console.log('[SIDEBAR] agentCards:', agentCards);
  console.log('[SIDEBAR] agentCards keys:', agentCards ? Object.keys(agentCards) : 'null');

  return (
    <aside className="w-80 bg-[#1a1e27] border-r border-gray-700 flex flex-col flex-shrink-0">
      <div className="p-4 border-b border-gray-700 flex-shrink-0">
        <h2 className="text-lg font-semibold text-gray-200 mb-2">Session Info</h2>
      </div>

      <div className="flex-1 p-4 space-y-4 overflow-y-auto min-h-0">
        {/* Agent ARN */}
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Agent ARN</h3>
          <div className="bg-[#23272f] border border-gray-600 rounded-lg p-3 text-xs text-gray-300 font-mono break-all">
            {agentArn || 'Not initialized'}
          </div>
        </div>

        {/* Session ID */}
        <div>
          <h3 className="text-sm font-medium text-gray-400 mb-2">Session ID</h3>
          <div className="bg-[#23272f] border border-gray-600 rounded-lg p-3 text-xs text-gray-300 font-mono break-all">
            {sessionId}
          </div>
        </div>

        {/* Agent Cards */}
        {agentCards && Object.keys(agentCards).length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-gray-400 mb-2">Sub-Agents</h3>
            <div className="space-y-3">
              {Object.entries(agentCards).map(([agentName, agentInfo]) => (
                <div key={agentName} className="bg-[#23272f] border border-gray-600 rounded-lg p-3">
                  <div className="text-sm font-semibold text-gray-200 mb-1">{agentName}</div>
                  <div className="text-xs text-gray-400 mb-2">{agentInfo.agent_card.description || 'No description'}</div>
                  <div className="space-y-1">
                    <div className="text-xs">
                      <span className="text-gray-500">Name:</span>
                      <span className="text-gray-300 ml-1">{agentInfo.agent_card.name}</span>
                    </div>
                    {agentInfo.agent_card.version && (
                      <div className="text-xs">
                        <span className="text-gray-500">Version:</span>
                        <span className="text-gray-300 ml-1">{agentInfo.agent_card.version}</span>
                      </div>
                    )}
                    <details className="text-xs">
                      <summary className="text-gray-500 cursor-pointer hover:text-gray-400">RPC URL</summary>
                      <div className="text-gray-300 font-mono break-all mt-1 ml-2">{agentInfo.agent_card.url}</div>
                    </details>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
