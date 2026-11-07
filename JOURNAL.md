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
* A Claude API to run Haiku 5.5 on the Pi

We don't need to buy a motor or wires, since we already have what we need.
 
I also planned how everything connects. The webcam plugs straight into the Pi with a USB cable, and the light allows the camera to send proper images to the Pi.
 
Finally for today, I used Claude to help me write a rough first version of the code for the Pi. It is not final, but it gives us something to build on. The code takes a picture of the item, decides if it is recycling or trash, and sends a signal for which bin it should go into. It also saves the result of every sort in a file, and in test mode we can mark each sort as right or wrong. This will let us calculate our accuracy and see if we hit our 85% goal.
 
I also looked at two ways for the Pi to decide what an item is:
 
* A program we train ourselves with our own photos, which works without internet
* A large AI program, which can recognize more items but needs internet

-Eeshan Pathak

# October 29 - Camera and Card Reader, Testing Claude, Marietta Rules
 
I bought two new parts for the Raspberry Pi:
 
* A camera
* A microSD card reader

Next, I set up Claude Haiku 5.5, an AI model that runs over the internet, on the Pi. I tested the camera and Claude with different objects. For each one:
 
* The Pi took a picture of the object
* The Pi sent the picture to Claude
* Claude told me if the item was recycling or trash

The tests worked.
 
Then I realized that different places have different trash and recycling laws, so our can would have to follow them. I researched the Marietta rules by reading the City of Marietta sanitation page. I tried the tests again, but this time I gave Claude those Marietta trash and recycling rules first. That worked too.
 
Finally, I realized that our can needs to work on its own, without depending on the internet. Next time, we will go back to training our own model to recognize items from pictures.
 
-Eeshan Pathak

# November 4 - Local AI, Rules App, Pi Launcher
 
Today I changed our sorter from using the Claude AI over the internet to using a local AI that runs on the Pi itself, and I used Claude to code this entire project. I trained the local AI with several images from TrashNet, a trash image collection on GitHub. Then I tested it to make sure it could tell different types of trash apart correctly.
 
I then made an app that can switch between different sets of recycling rules (called rulesets), since every city has different recycling laws. There are three ways to use it:
 
* Pick a preset that already has the recycling laws from a city
* Upload a document to add laws and recycling rules from other cities
* Write our own custom recycling rules

The website saves these presets inside the app. I had to make 5 versions of the app to give it a better user interface.
 
After that, I made a launcher on the Pi with 5 functions:
 
1. Launch the app so it works on your Wi-Fi network
2. Launch a public link so the app can be used on the public internet
3. Run the trash sorter itself
4. Retrain the AI using a set of images
5. Test the camera

Finally, I made a logo for our website and made the website more aesthetically pleasing.

I need to buy a few items because the Pi keeps overheating:

* Cooling pads
* A fan
* A heatsink
 
Our main problem now is that every time we launch the website from the Pi, the web address changes. We are deciding between two options: keep the changing address and make it easier to open with a QR code, or buy a permanent domain (a web address that doesn't change) on Cloudflare. We will focus on this problem next time.
 
-Eeshan Pathak

# November 6 - Planning for CAD, Permanent Link, QR Code

My goal here is to make an actual functional CAD model that we can prototype. Of course, not a full fidelity version using industry parts that would be on something like this if it existed as a commercial product, but rather using simple and cheap parts that will still demonstrate the functional effectiveness of the sorter without being too complex or costing too much. I want to start by figuring out how to actually drive the tray that deposits trash in either bin. The easiest solution that we can do using parts that we already have on hand is to drive it using a 42-40 NEMA 17 stepper motor from an old Ender 3 3D printer as well as a L293D motor driver connected to our Raspberry Pi. The real problem is that standard stepper motors simply do not have a high enough torque output to effectively turn the tray while it's loaded with mass from the trash deposit without being back driven or stalling. To fix this, some sort of reduction must be placed between the motor and the tray.

-Rahdeen Sigari

Before today, the public link for the EZtrash website changed every time we started it, so we had to send people a new link each time. I set up a permanent link using Tailscale, a free service that gives the Raspberry Pi its own web address that never changes. Now the website always has the same link, and it works from any phone or computer, even on a different network.

This required updating two parts of our project:

* The launcher: I added options to set up Tailscale, turn the public link on, and turn it off. The launcher also shows the link on its screen.
* The app: it now finds the Tailscale link by itself and shows it when it starts.

I also set up a QR code that can be scanned to open the website. It shows up in two places:

* On the website, using a QR button at the top
* In the terminal when the app starts

Anyone can scan the QR code with their phone camera to open the website. They still need the access code to change any trash and recycling rules.

-Eeshan Pathak

# November 7 - Reduction Calcuations

I'm going to assume the maximum mass that the sorter will have to deal with at any time is 0.5kg. Additionally, I'm also going to make the tray be 240mm wide, meaning that the furthest away an object can be is 120mm. First I can calculate gravitational force acting upon the tray:

F = 0.5kg * 9.81m/s^2 = 4.905N

Then, knowing that the trash is going to be a maximum of 120mm away from the center I can calculate the holding torque:

τ = 4.905N * 0.12m = 0.589 Nm

Meaning that the stepper needs to produce at least 0.589Nm just to stop the object from back driving the tray.

I of course also need to account for acceleration, first I need the moment of inertia of the object, which I can assume to be a single point of force:

I = 0.5kg * (0.12m)^2 = 0.0072 kg*m^2

And the moment of inertia of the plate itself:

I = (1/12) * 0.2kg * (0.24m)^2 = 0.00096 kg*m^2

Meaning that the total inertia is 0.00816 kg*m^2

So I know how much torque I need to actually hold the object, but now I also need to know how much more torque I need to accelerate it to 35 degrees. My goal is to get to the target in around one second.

I first need to calculate angular displacement to then find acceleration torque. I'm using a target time of one second here:

(Where 0.6019 is 35 degrees in radians)

α = 4(0.6019) / 1^2 = 2.4436 rad/s^2

With that I can calculate the acceleration torque:

τ = (0.00816 kg*m^2) * (2.4436 rad/s^2) = 0.0199 Nm

Adding those two torque values gives us the theoretical torque requirement:

0.589Nm + 0.0199Nm = 0.609 Nm

With that, assuming that the motor has a torque of around 0.22 Nm when running (based off of the manufacturer torque curve) and the efficiency is 80%, I can model how different gear ratios effect output torque:

τ(x) = 0.22Nm * x * 0.80

τ(9) = 1.584 Nm

If I assume a nominal torque output of 1.50 Nm, I can find that around 9:1 is the optimal reduction ratio to achieve my ideal torque output while preserving speed. This also gives us a safety margin of around 2.6.

-Rahdeen Sigari
