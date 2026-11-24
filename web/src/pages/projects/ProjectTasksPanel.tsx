import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ListTodo, Trash2 } from 'lucide-react'

import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { apiRequest } from '../../lib/http'
import { useI18n } from '../../lib/i18n'
import type { ProjectTask } from '../../lib/types'

export function ProjectTasksPanel({ projectId }: { projectId: string }) {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const tasks = useQuery({
    queryKey: ['project-tasks', projectId],
    queryFn: () =>
      apiRequest<ProjectTask[]>(`/project-tasks?project_id=${projectId}`),
  })

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['project-tasks', projectId] })

  const update = async (task: ProjectTask, status: ProjectTask['status']) => {
    await apiRequest(`/project-tasks/${task.id}`, {
      method: 'PATCH',
      body: { status },
    })
    await refresh()
  }

  const remove = async (task: ProjectTask) => {
    await apiRequest(`/project-tasks/${task.id}`, { method: 'DELETE' })
    await refresh()
  }

  return (
    <div className="rounded-2xl border border-border bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-border px-5 py-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
          <ListTodo className="h-4 w-4 text-accent" />
          {t('tasks.title')}
        </h2>
        <span className="text-xs text-ink-muted">
          {t('tasks.count', { count: tasks.data?.length ?? 0 })}
        </span>
      </div>
      <div className="space-y-2 px-5 py-4">
        {tasks.data !== undefined && tasks.data.length === 0 && (
          <p className="text-xs text-ink-muted">{t('tasks.empty')}</p>
        )}
        {(tasks.data ?? []).map((task) => (
          <div
            key={task.id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border px-3 py-2 text-xs"
          >
            <input
              type="checkbox"
              checked={task.status === 'done'}
              onChange={(event) =>
                void update(task, event.target.checked ? 'done' : 'todo')
              }
            />
            <span
              className={
                task.status === 'done' ? 'text-ink-muted line-through' : 'text-ink'
              }
            >
              {task.title}
            </span>
            <Badge
              tone={
                task.priority === 'high'
                  ? 'danger'
                  : task.priority === 'low'
                    ? 'neutral'
                    : 'accent'
              }
            >
              {task.priority}
            </Badge>
            <select
              className="ml-auto h-7 rounded-md border border-border bg-surface px-1 text-[11px] text-ink"
              value={task.status}
              onChange={(event) =>
                void update(task, event.target.value as ProjectTask['status'])
              }
            >
              <option value="todo">{t('tasks.todo')}</option>
              <option value="doing">{t('tasks.doing')}</option>
              <option value="done">{t('tasks.done')}</option>
            </select>
            <Button variant="ghost" size="sm" onClick={() => void remove(task)}>
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        ))}
      </div>
    </div>
  )
}