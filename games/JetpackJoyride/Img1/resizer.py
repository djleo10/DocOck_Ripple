import pygame, sys
pygame.init()
pygame.image.save(  pygame.transform.scale(  pygame.image.load(input("name of image: ")), [int(i) for i in input("resolution: ").split(", ")]), input("new name of image: ")  )
pygame.quit()
sys.exit()
