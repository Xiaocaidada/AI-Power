import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { Button } from '../../components/ui/button'
import { Dialog } from '../../components/ui/dialog'
import { Input } from '../../components/ui/input'
import { errorTextKey } from '../../lib/errorText'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type {
  CodeBlock,
  CodeSnippet,
  KnowledgeBase,
  Project,
  ProjectTask,
  SavedDocument,
  TaskCandidate,
} from '../../lib/types'

interface ReuseDialogProps {
  open: boolean
  conversationId: string
  messageId: string
  onClose: () => void
}

export function ReuseDialog({
  open,
  conversationId,
  messageId,
  onClose,
}: ReuseDialogProps) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const [kbId, setKbId] = useState('')
  const [title, setTitle] = useState('')
  const [projectId, setProjectId] = useState('')
  const [selectedTasks, setSelectedTasks] = useState<string[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const kbs = useQuery({
    queryKey: ['kbs'],
    queryFn: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
    enabled: open,
    staleTime: 60_000,
  })
  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiRequest<Project[]>('/projects'),
    enabled: open,
    staleTime: 60_000,
  })
  const blocks = useQuery({
    queryKey: ['code-blocks', conversationId, messageId],
    queryFn: () =>
      apiRequest<CodeBlock[]>(
        `/conversations/${conversationId}/messages/${messageId}/code-blocks`,
      ),
    enabled: open,
  })
  const candidates = useQuery({
    queryKey: ['task-candidates', conversationId, messageId],
    queryFn: () =>
      apiRequest<TaskCandidate[]>(
        `/conversations/${conversationId}/messages/${messageId}/task-candidates`,
      ),
    enabled: open,
  })

  const saveKnowledge = async () => {
    if (kbId === '') return
    setBusy('knowledge')
    setError(null)
    setNotice(null)
    try {
      const result = await apiRequest<SavedDocument>(
        `/conversations/${conversationId}/messages/${messageId}/save-to-knowledge`,
        { method: 'POST', body: { kb_id: kbId, title } },
      )
      setNotice(
        result.duplicate
          ? t('reuse.knowledgeDuplicate')
          : t('reuse.knowledgeSaved'),
      )
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  const saveCode = async (block: CodeBlock) => {
    setBusy(`code-${block.index}`)
    setError(null)
    setNotice(null)
    try {
      await apiRequest<CodeSnippet>('/code-snippets', {
        method: 'POST',
        body: {
          title: block.title,
          language: block.language,
          code: block.code,
          conversation_id: conversationId,
          message_id: messageId,
        },
      })
      setNotice(t('reuse.codeSaved'))
      await queryClient.invalidateQueries({ queryKey: ['code-snippets'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  const saveTasks = async () => {
    if (projectId === '' || selectedTasks.length === 0) return
    setBusy('tasks')
    setError(null)
    setNotice(null)
    try {
      const rows = (candidates.data ?? []).filter((task) =>
        selectedTasks.includes(task.title),
      )
      await apiRequest<ProjectTask[]>('/project-tasks', {
        method: 'POST',
        body: {
          project_id: projectId,
          conversation_id: conversationId,
          message_id: messageId,
          tasks: rows,
        },
      })
      setNotice(t('reuse.tasksSaved'))
      await queryClient.invalidateQueries({ queryKey: ['project-tasks', projectId] })
      await queryClient.invalidateQueries({ queryKey: ['project-tasks'] })
    } catch (caught) {
      setError(t(errorTextKey(caught)))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('reuse.title')}
      footer={
        <Button variant="secondary" size="sm" onClick={onClose}>
          {t('common.close')}
        </Button>
      }
    >
      <div className="space-y-4">
        <section className="rounded-xl border border-border p-3">
          <h3 className="text-sm font-medium text-ink">{t('reuse.toKnowledge')}</h3>
          <p className="mt-0.5 text-xs text-ink-muted">{t('reuse.toKnowledgeHint')}</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
            <select
              className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
              value={kbId}
              onChange={(event) => setKbId(event.target.value)}
            >
              <option value="">{t('reuse.selectKb')}</option>
              {(kbs.data ?? []).map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
            <Input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={t('reuse.documentTitle')}
            />
            <Button
              size="sm"
              disabled={kbId === '' || busy === 'knowledge'}
              onClick={() => void saveKnowledge()}
            >
              {t('reuse.save')}
            </Button>
          </div>
        </section>

        <section className="rounded-xl border border-border p-3">
          <h3 className="text-sm font-medium text-ink">{t('reuse.codeBlocks')}</h3>
          <p className="mt-0.5 text-xs text-ink-muted">{t('reuse.codeBlocksHint')}</p>
          {blocks.isLoading && (
            <p className="mt-2 text-xs text-ink-muted">{t('common.loading')}</p>
          )}
          {blocks.data !== undefined && blocks.data.length === 0 && (
            <p className="mt-2 text-xs text-ink-muted">{t('reuse.noCode')}</p>
          )}
          <div className="mt-2 space-y-2">
            {(blocks.data ?? []).map((block) => (
              <div key={block.index} className="rounded-lg bg-surface-muted/40 p-2">
                <div className="flex items-center gap-2 text-xs text-ink-muted">
                  <span className="font-mono text-ink">{block.language}</span>
                  <span className="truncate">{block.title}</span>
                  <Button
                    size="sm"
                    variant="secondary"
                    className="ml-auto"
                    disabled={busy === `code-${block.index}`}
                    onClick={() => void saveCode(block)}
                  >
                    {t('reuse.saveSnippet')}
                  </Button>
                </div>
                <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap text-[11px] text-ink-muted">
                  {block.code}
                </pre>
              </div>
            ))}
          </div>
          <Link
            to="/snippets"
            className="mt-2 inline-block text-xs text-accent underline"
          >
            {t('reuse.viewSnippets')}
          </Link>
        </section>

        <section className="rounded-xl border border-border p-3">
          <h3 className="text-sm font-medium text-ink">{t('reuse.toProject')}</h3>
          <p className="mt-0.5 text-xs text-ink-muted">{t('reuse.toProjectHint')}</p>
          {candidates.data !== undefined && candidates.data.length === 0 && (
            <p className="mt-2 text-xs text-ink-muted">{t('reuse.noTasks')}</p>
          )}
          {candidates.data !== undefined && candidates.data.length > 0 && (
            <>
              <div className="mt-2 flex flex-wrap gap-2">
                <select
                  className="h-9 rounded-lg border border-border bg-surface px-2 text-sm text-ink"
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  <option value="">{t('reuse.selectProject')}</option>
                  {(projects.data ?? []).map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.name}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  disabled={
                    projectId === '' ||
                    selectedTasks.length === 0 ||
                    busy === 'tasks'
                  }
                  onClick={() => void saveTasks()}
                >
                  {t('reuse.saveTasks')}
                </Button>
              </div>
              <div className="mt-2 space-y-1">
                {(candidates.data ?? []).map((task) => (
                  <label
                    key={task.title}
                    className="flex items-center gap-2 text-xs text-ink"
                  >
                    <input
                      type="checkbox"
                      checked={selectedTasks.includes(task.title)}
                      onChange={(event) => {
                        setSelectedTasks((prev) =>
                          event.target.checked
                            ? [...prev, task.title]
                            : prev.filter((item) => item !== task.title),
                        )
                      }}
                    />
                    {task.title}
                  </label>
                ))}
              </div>
            </>
          )}
        </section>

        {notice !== null && <p className="text-xs text-success">{notice}</p>}
        {error !== null && <p className="text-xs text-danger">{error}</p>}
      </div>
    </Dialog>
  )
}