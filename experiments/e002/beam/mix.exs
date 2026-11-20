defmodule AgentNativeE002Beam.MixProject do
  use Mix.Project

  def project do
    [
      app: :agent_native_e002_beam,
      version: "0.1.0",
      elixir: "~> 1.20",
      start_permanent: Mix.env() == :prod,
      deps: []
    ]
  end

  def application do
    [extra_applications: [:logger], mod: {AgentNativeE002Beam.Application, []}]
  end
end
