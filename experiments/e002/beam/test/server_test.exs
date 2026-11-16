defmodule AgentNativeE002Beam.ServerTest do
  use ExUnit.Case, async: true

  alias AgentNativeE002Beam.Server

  test "health route is deterministic" do
    assert Server.route("GET", "/health") == {:response, 200, "ok"}
  end

  test "work route accepts bounded durations" do
    assert Server.route("GET", "/work?ms=20") == {:work, 20}
    assert Server.route("GET", "/work?ms=900") == {:work, 900}
  end

  test "invalid work duration is rejected" do
    assert Server.route("GET", "/work?ms=invalid") == {:response, 400, "invalid ms"}
    assert Server.route("GET", "/work?ms=9000") == {:response, 400, "invalid ms"}
  end

  test "unknown path and method have stable outcomes" do
    assert Server.route("GET", "/missing") == {:response, 404, "not found"}
    assert Server.route("POST", "/health") == {:response, 405, "method not allowed"}
  end
end
