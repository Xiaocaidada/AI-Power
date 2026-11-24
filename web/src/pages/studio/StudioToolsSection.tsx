import { useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { useMemo, useState } from 'react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { PopoverSelect } from '../../components/ui/popover-select'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  AgentMcpTool,
  AgentToolCatalog,
  AgentToolTestResult,
} from '../../lib/types'

interface StudioToolsSectionProps {
  agentId: string
  tools: string[]
  onChange: (tools: string[]) => void
}

function toolLabel(tool: string, mcpTools: AgentMcpTool[]): string {
  const match = mcpTools.find((item) => item.ref === tool)
  if (match !== undefined) return `MCP · ${match.name}`
  if (tool.startsWith('mcp:')) {
    const parts = tool.split(':')
    return `MCP · ${parts.slice(2).join(':')}`
  }
  return tool
}

export function StudioToolsSection({
  agentId,
  tools,
  onChange,
}: StudioToolsSectionProps) {
  const { t } = useI18n()
  const [serverId, setServerId] = useState('')
  const [testTool, setTestTool] = useState('')
  const [testArgs, setTestArgs] = useState('{}')
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState<AgentToolTestResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const catalog = useQuery({
    queryKey: ['agent-tool-catalog'],
    queryFn: () => apiRequest<AgentToolCatalog>('/agent-tools/catalog'),
    staleTime: 60_000,
  })
  const mcpTools = useQuery({
    queryKey: ['agent-mcp-tools', serverId],
    queryFn: () =>
      apiRequest<AgentMcpTool[]>(
        `/agent-tools/mcp?server_id=${encodeURIComponent(serverId)}`,
      ),
    enabled: serverId !== '',
  })

  const discovered = useMemo(() => mcpTools.data ?? [], [mcpTools.data])

  const toggle = (tool: string) => {
    if (tools.includes(tool)) {
      onChange(tools.filter((item) => item !== tool))
      if (testTool === tool) setTestTool('')
      return
    }
    onChange([...tools, tool])
  }

  const runTest = async () => {
    const tool = testTool === '' ? tools[0] : testTool
    if (tool === undefined) return
    let parsed: Record<string, unknown>
    try {
      const candidate: unknown = JSON.parse(testArgs === '' ? '{}' : testArgs)
      if (
        candidate === null ||
        typeof candidate !== 'object' ||
        Array.isArray(candidate)
      ) {
        throw new Error('not-an-object')
      }
      parsed = candidate as Record<string, unknown>
    } catch {
      setError(t('studio.toolArgsInvalid'))
      return
    }
    setTesting(true)
    setError(null)
    setResult(null)
    try {
      const response = await apiRequest<AgentToolTestResult>(
        `/agents/${agentId}/tools/test`,
        { method: 'POST', body: { tool, arguments: parsed } },
      )
      setResult(response)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('errors.generic'))
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-surface-muted/40 p-3">
      <p className="text-xs font-medium text-ink">{t('studio.toolEcosystem')}</p>
      <p className="mt-0.5 text-[10px] text-ink-muted">{t('studio.toolEcosystemHint')}</p>

      <div className="mt-2 flex flex-wrap gap-3">
        {(catalog.data?.builtin ?? []).map((tool) => (
          <label key={tool.name} className="flex items-center gap-1.5 text-xs text-ink">
            <input
              type="checkbox"
              checked={tools.includes(tool.name)}
              onChange={() => toggle(tool.name)}
            />
            {tool.name}
          </label>
        ))}
      </div>

      {(catalog.data?.mcp_servers.length ?? 0) > 0 && (
        <div className="mt-3 space-y-2">
          <PopoverSelect
            label={t('studio.mcpServer')}
            value={serverId}
            options={[
              { value: '', label: t('studio.mcpServerPlaceholder') },
              ...(catalog.data?.mcp_servers ?? []).map((server) => ({
                value: server.id,
                label: server.name,
              })),
            ]}
            onChange={(value) => {
              setServerId(value)
              setError(null)
            }}
          />
          {serverId !== '' && mcpTools.isLoading && (
            <p className="text-[11px] text-ink-muted">{t('studio.mcpLoading')}</p>
          )}
          {serverId !== '' && mcpTools.isError && (
            <p className="text-[11px] text-danger">{t('studio.mcpUnavailable')}</p>
          )}
          {discovered.length > 0 && (
            <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border bg-surface p-2">
              {discovered.map((tool) => (
                <label
                  key={tool.ref}
                  className="flex items-start gap-2 text-[11px] text-ink"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={tools.includes(tool.ref)}
                    onChange={() => toggle(tool.ref)}
                  />
                  <span>
                    <span className="font-mono">{tool.name}</span>
                    {tool.description && (
                      <span className="block text-[10px] text-ink-muted">
                        {tool.description}
                      </span>
                    )}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      {tools.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {tools.map((tool) => (
            <button
              key={tool}
              type="button"
              onClick={() => toggle(tool)}
              className="rounded-full border border-border bg-surface px-2 py-0.5 text-[10px] text-ink-muted hover:border-danger/50 hover:text-danger"
            >
              {toolLabel(tool, discovered)} ×
            </button>
          ))}
        </div>
      )}

      <div className="mt-3 rounded-lg border border-border bg-surface p-2">
        <div className="flex flex-wrap items-center gap-2">
          <PopoverSelect
            label={t('studio.toolTest')}
            value={testTool === '' ? tools[0] ?? '' : testTool}
            options={tools.map((tool) => ({
              value: tool,
              label: toolLabel(tool, discovered),
            }))}
            onChange={setTestTool}
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={testing || tools.length === 0}
            onClick={() => void runTest()}
          >
            <Play className="h-3.5 w-3.5" />
            {testing ? t('studio.toolTesting') : t('studio.toolTestRun')}
          </Button>
          {result !== null && (
            <Badge tone={result.ok ? 'success' : 'danger'}>
              {result.ok ? t('studio.toolTestOk') : result.error_code ?? 'error'}
            </Badge>
          )}
        </div>
        <textarea
          value={testArgs}
          onChange={(event) => setTestArgs(event.target.value)}
          placeholder='{"expression": "1 + 1"}'
          className="mt-2 min-h-14 w-full rounded-lg border border-border bg-surface px-2 py-1.5 font-mono text-[11px] text-ink"
        />
        {result !== null && (
          <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface-muted p-2 text-[10px] text-ink">
            {result.output || result.error}
          </pre>
        )}
        {error !== null && <p className="mt-2 text-[11px] text-danger">{error}</p>}
      </div>
    </div>
  )
}