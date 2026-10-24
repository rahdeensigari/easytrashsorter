# October 21 - Design Criteria, Initial Survey, Rough CAD

We first started our project by establishing some design criteria that we want to follow:

Necessary:
- The product must mechanically be able to sort between landfill waste and recyclables.
- The product must fit within the profile of a normal trashcan (3x1.5x3ft).
- The product must be able to spread awareness towards the environment and encourage more people to pay attention to where they place their trash.
- Easy access to the bins
- One chute for trash to go into

Nice to have:
- 85% sorting accuracy.
- A window to show the mechanical process

Out of scope:
- Sort a large group of trash into their respective categories when everything is placed in at once (majority will determine the grouping).

-Eeshan Pathak, Rahdeen Sigari

We also created a survey to help gauge if people pay attention to where they deposit their trash, and why they don't. We will spread this survey as much as we can around our school to get a set of responses to back up the creation of our project.

-Reise Hebert, Rahdeen Sigari

Finally for today, we created a rough CAD model of what we want the final product to look like. This was not made to show technical specifications, but rather to help visualize the concept:

<img width="512" height="279" alt="image" src="https://github.com/user-attachments/assets/6eb3270b-e953-4728-98cf-05a3e44a44f0" />

-Rahdeen Sigari

# October 23 - Raspberry Pi Parts List, Setup Plan, Starter Code
 
We decided to focus on the Raspberry Pi, a tiny computer that will act as the brain of our sorter. I used Claude, an AI assistant, to help me research what parts we need and how the Pi works. We already have a Pi, a memory card, and a power cord for it, so I made a list of the other parts we need for the prototype:
 
Necessary:
 
* A webcam to take a picture of each piece of trash
* A light so every picture looks the same
We don't need to buy a motor or wires, since we already have what we need.
 
I also planned how everything connects. The webcam plugs straight into the Pi with a USB cable, and the light allows the camera to send proper images to the Pi.
 
Finally for today, I wrote a rough first version of the code for the Pi. It is not final, but it gives us something to build on. The code takes a picture of the item, decides if it is recycling or trash, and sends a signal for which bin it should go into. It also saves the result of every sort in a file, and in test mode we can mark each sort as right or wrong. This will let us calculate our accuracy and see if we hit our 85% goal.
 
I also looked at two ways for the Pi to decide what an item is:
 
* A program we train ourselves with our own photos, which works without internet
* A large AI program, which can recognize more items but needs internet

-Eeshan Pathak
