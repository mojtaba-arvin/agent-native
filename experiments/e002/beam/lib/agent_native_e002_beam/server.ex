defmodule AgentNativeE002Beam.Server do
  @max_concurrent 64
  @deadline_ms 750

  def main do
    {:ok, listener} =
      :gen_tcp.listen(8080, [
        :binary,
        packet: :line,
        active: false,
        reuseaddr: true,
        ip: {127, 0, 0, 1},
        backlog: 1024
      ])

    counter = :atomics.new(1, signed: false)
    accept_loop(listener, counter)
  end

  def route("GET", "/health"), do: {:response, 200, "ok"}
  def route("GET", "/stream"), do: :stream

  def route("GET", target) do
    uri = URI.parse(target)

    if uri.path == "/work" do
      case decode_ms(uri.query) do
        {:ok, ms} when ms in 0..5000 -> {:work, ms}
        _ -> {:response, 400, "invalid ms"}
      end
    else
      {:response, 404, "not found"}
    end
  end

  def route(_method, _target), do: {:response, 405, "method not allowed"}

  defp decode_ms("ms=" <> value) when value != "" do
    if String.match?(value, ~r/^[0-9]+$/) do
      case Integer.parse(value) do
        {number, ""} when number <= 5000 -> {:ok, number}
        _ -> :error
      end
    else
      :error
    end
  end

  defp decode_ms(_query), do: :error

  defp accept_loop(listener, counter) do
    case :gen_tcp.accept(listener) do
      {:ok, socket} ->
        Task.start(fn -> handle(socket, counter) end)
        accept_loop(listener, counter)

      {:error, :closed} ->
        :ok

      {:error, reason} ->
        raise "accept failed: #{inspect(reason)}"
    end
  end

  defp handle(socket, counter) do
    active = :atomics.add_get(counter, 1, 1)

    if active > @max_concurrent do
      :atomics.sub(counter, 1, 1)
      send_response(socket, 503, "overloaded")
      :gen_tcp.close(socket)
    else
      try do
        with {:ok, request_line} <- :gen_tcp.recv(socket, 0, 5000),
             :ok <- read_headers(socket),
             [method, target, _version] <- String.split(String.trim(request_line), " ", parts: 3) do
          dispatch(socket, route(method, target))
        else
          _ -> send_response(socket, 400, "invalid request")
        end
      after
        :atomics.sub(counter, 1, 1)
        :gen_tcp.close(socket)
      end
    end
  end

  defp read_headers(socket) do
    case :gen_tcp.recv(socket, 0, 5000) do
      {:ok, "\r\n"} -> :ok
      {:ok, _header} -> read_headers(socket)
      {:error, reason} -> {:error, reason}
    end
  end

  defp dispatch(socket, {:response, status, body}), do: send_response(socket, status, body)

  defp dispatch(socket, {:work, ms}) when ms > @deadline_ms do
    Process.sleep(@deadline_ms)
    send_response(socket, 504, "deadline exceeded")
  end

  defp dispatch(socket, {:work, ms}) do
    Process.sleep(ms)
    send_response(socket, 200, "completed:#{ms}")
  end

  defp dispatch(socket, :stream) do
    :gen_tcp.send(socket, [
      "HTTP/1.1 200 OK\r\n",
      "content-type: application/octet-stream\r\n",
      "transfer-encoding: chunked\r\n",
      "connection: close\r\n\r\n"
    ])

    Enum.each(1..3, fn index ->
      chunk = "chunk-#{index}\n"
      :gen_tcp.send(socket, [Integer.to_string(byte_size(chunk), 16), "\r\n", chunk, "\r\n"])
    end)

    :gen_tcp.send(socket, "0\r\n\r\n")
  end

  defp send_response(socket, status, body) do
    reason =
      case status do
        200 -> "OK"
        400 -> "Bad Request"
        404 -> "Not Found"
        405 -> "Method Not Allowed"
        503 -> "Service Unavailable"
        504 -> "Gateway Timeout"
      end

    :gen_tcp.send(socket, [
      "HTTP/1.1 #{status} #{reason}\r\n",
      "content-type: text/plain; charset=utf-8\r\n",
      "content-length: #{byte_size(body)}\r\n",
      "connection: close\r\n\r\n",
      body
    ])
  end
end
