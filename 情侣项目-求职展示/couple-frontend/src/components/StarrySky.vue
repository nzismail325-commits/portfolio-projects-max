<template>
  <canvas ref="canvasRef" class="starry-sky-canvas"></canvas>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'

const canvasRef = ref(null)
let animationFrameId = null

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')

  let stars = []

  const resizeCanvas = () => {
    canvas.width = window.innerWidth
    canvas.height = window.innerHeight
    const numStars = Math.floor((canvas.width * canvas.height) / 3000)
    stars = []
    for (let i = 0; i < numStars; i++) {
      stars.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        radius: Math.random() * 1.5 + 0.7,
        alpha: Math.random() * 0.6 + 0.4,
        twinkleSpeed: Math.random() * 0.015,
        twinkleDirection: 1,
        vx: (Math.random() - 0.5) * 0.2,
        vy: (Math.random() - 0.5) * 0.2
      })
    }
  }

  const draw = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    stars.forEach((star) => {
      star.x += star.vx
      star.y += star.vy
      star.alpha += star.twinkleSpeed * star.twinkleDirection
      if (star.alpha >= 1 || star.alpha <= 0.4) {
        star.twinkleDirection *= -1
      }
      if (star.x < 0) star.x = canvas.width
      if (star.x > canvas.width) star.x = 0
      if (star.y < 0) star.y = canvas.height
      if (star.y > canvas.height) star.y = 0
      ctx.beginPath()
      ctx.arc(star.x, star.y, star.radius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(255, 255, 255, ${star.alpha})`
      ctx.shadowBlur = 12
      ctx.shadowColor = 'white'
      ctx.fill()
    })
    animationFrameId = requestAnimationFrame(draw)
  }

  let resizeTimer
  const onResize = () => {
    clearTimeout(resizeTimer)
    resizeTimer = setTimeout(() => {
      cancelAnimationFrame(animationFrameId)
      resizeCanvas()
      draw()
    }, 200)
  }

  resizeCanvas()
  draw()
  window.addEventListener('resize', onResize)

  onBeforeUnmount(() => {
    cancelAnimationFrame(animationFrameId)
    window.removeEventListener('resize', onResize)
  })
})
</script>

<style scoped>
.starry-sky-canvas {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  display: block;
  z-index: 999;
  pointer-events: none;
}
</style>
