FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
RUN go build -o /prediction-engine .

FROM alpine:3.20
COPY --from=build /prediction-engine /prediction-engine
ENV PORT=8090
EXPOSE 8090
ENTRYPOINT ["/prediction-engine"]
