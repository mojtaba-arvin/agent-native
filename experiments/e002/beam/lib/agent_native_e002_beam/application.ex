defmodule AgentNativeE002Beam.Application do
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      %{
        id: :e002_http_server,
        start: {Task, :start_link, [fn -> AgentNativeE002Beam.Server.main() end]},
        restart: :permanent,
        shutdown: 5_000,
        type: :worker
      }
    ]

    Supervisor.start_link(children, strategy: :one_for_one, name: __MODULE__.Supervisor)
  end
end
