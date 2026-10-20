document.querySelectorAll('[data-wallet-button]').forEach(button => {
  button.addEventListener('click', async () => {
    button.disabled = true
    try {
      const config = await fetch('/wallet/config', { cache: 'no-store' }).then(response => response.json())
      if (!config.projectId) throw new Error('Wallet connection needs a Reown project ID. Set CLINTR_REOWN_PROJECT_ID in the deployment environment.')
      const { openWallet } = await import('/assets/wallet.bundle.js')
      await openWallet()
    } catch (error) {
      let toast = document.getElementById('wallet-toast')
      if (!toast) {
        toast = document.createElement('div')
        toast.id = 'wallet-toast'
        document.body.append(toast)
      }
      toast.textContent = error.message || 'Wallet connection could not be loaded. Please try again.'
      console.error(error)
    } finally {
      button.disabled = false
    }
  })
})
